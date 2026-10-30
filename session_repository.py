import sqlite3
import json
from dataclasses import asdict, dataclass, replace
from contextlib import closing, contextmanager
from datetime import datetime
from typing import List, Tuple

import config
from zoneinfo import ZoneInfo

FOCUS_SCOPES = ("shared", "per_subject")


@dataclass(frozen=True)
class ActiveTimer:
    session_id: str
    mode: str
    subject: str
    phase: str
    total_seconds: int
    remaining_seconds: int
    return_to_choice: bool = False
    suspended_focus: "ActiveTimer | None" = None


def _create_progress_tables(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS active_timer (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        session_id TEXT NOT NULL, mode TEXT NOT NULL, subject TEXT NOT NULL,
        phase TEXT NOT NULL, total_seconds INTEGER NOT NULL CHECK (total_seconds >= 0),
        remaining_seconds INTEGER NOT NULL CHECK (remaining_seconds >= 0),
        return_to_choice INTEGER NOT NULL CHECK (return_to_choice IN (0, 1))
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS timer_completions (
        session_id TEXT PRIMARY KEY
    )""")


def _migrate_active_timer(connection):
    cursor = connection.execute("PRAGMA table_info(active_timer)")
    existing = {row[1] for row in cursor.fetchall()}
    expected = {"id", "session_id", "mode", "subject", "phase",
                "total_seconds", "remaining_seconds", "return_to_choice"}
    if existing and not expected.issubset(existing):
        connection.execute("DROP TABLE active_timer")
        _create_progress_tables(connection)
    elif existing != expected:
        if existing != expected | {"suspended_focus"}:
            connection.execute("DROP TABLE active_timer")
            _create_progress_tables(connection)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(active_timer)")}
    if "suspended_focus" not in columns:
        connection.execute("ALTER TABLE active_timer ADD COLUMN suspended_focus TEXT")


def _write_active_timer(connection, timer):
    connection.execute("""INSERT OR REPLACE INTO active_timer
        (id, session_id, mode, subject, phase, total_seconds, remaining_seconds, return_to_choice, suspended_focus)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (timer.session_id, timer.mode, timer.subject, timer.phase,
         timer.total_seconds, timer.remaining_seconds, int(timer.return_to_choice),
         json.dumps(asdict(timer.suspended_focus)) if timer.suspended_focus else None))


def _migrate_shared_focus(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS shared_focus_progress (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0),
        migration_version INTEGER NOT NULL CHECK (migration_version = 1)
    )""")
    if connection.execute("SELECT 1 FROM shared_focus_progress WHERE id = 1").fetchone():
        return
    row = connection.execute(
        "SELECT elapsed_seconds FROM subject_focus_progress WHERE subject = 'Umum'"
    ).fetchone()
    seconds = row[0] if row else 0
    active = connection.execute("""SELECT mode, phase, total_seconds, suspended_focus
        FROM active_timer WHERE id = 1""").fetchone()
    if active and active[0] == "Pomodoro":
        if active[1] == "focus":
            seconds = config.POMODORO_FOCUS_SECONDS - active[2]
        elif active[1] == "break" and active[3]:
            try:
                focus = ActiveTimer(**json.loads(active[3]))
                seconds = config.POMODORO_FOCUS_SECONDS - focus.total_seconds
            except (TypeError, ValueError) as error:
                raise sqlite3.DatabaseError("Invalid suspended focus") from error
        elif active[1] == "choice":
            seconds = 0
    if type(seconds) is not int or not 0 <= seconds < config.POMODORO_FOCUS_SECONDS:
        raise sqlite3.DatabaseError("Invalid accumulated focus progress")
    connection.execute("INSERT INTO shared_focus_progress VALUES (1, ?, 1)", (seconds,))


def load_active_timer():
    with _pomodoro_transaction() as connection:
        row = connection.execute("""SELECT session_id, mode, subject, phase,
            total_seconds, remaining_seconds, return_to_choice, suspended_focus FROM active_timer WHERE id = 1""").fetchone()
        if row is None:
            return None
        try:
            suspended = ActiveTimer(**json.loads(row[-1])) if row[-1] else None
        except (TypeError, ValueError) as error:
            raise sqlite3.DatabaseError("Invalid suspended focus") from error
        timer = ActiveTimer(*row[:6], bool(row[6]), suspended)
        if suspended is not None and (
                timer.phase != "break" or suspended.phase != "focus"
                or suspended.mode != "Pomodoro" or suspended.subject != timer.subject
                or not suspended.session_id or suspended.suspended_focus is not None
                or type(suspended.total_seconds) is not int
                or type(suspended.remaining_seconds) is not int
                or not 0 < suspended.remaining_seconds <= suspended.total_seconds):
            raise sqlite3.DatabaseError("Invalid suspended focus")
        if (type(timer.total_seconds) is not int or type(timer.remaining_seconds) is not int
                or timer.total_seconds <= 0 or timer.remaining_seconds < 0
                or timer.mode not in ("Manual", "Pomodoro")
                or timer.phase not in ("manual", "focus", "break", "choice", "done")
                or timer.remaining_seconds > timer.total_seconds
                or not timer.session_id
                or (timer.phase in ("choice", "done") and timer.remaining_seconds != 0)
                or (timer.phase == "manual" and timer.mode != "Manual")
                or (timer.phase in ("focus", "break", "choice") and timer.mode != "Pomodoro")):
            raise sqlite3.DatabaseError("Invalid saved timer progress")
        return timer


def save_active_timer(timer):
    with _pomodoro_transaction() as connection:
        _write_active_timer(connection, timer)


def clear_active_timer():
    with _pomodoro_transaction() as connection:
        connection.execute("DELETE FROM active_timer")


def reset_active_timer(timer):
    """Save elapsed Pomodoro focus once and clear progress atomically."""
    focus = timer
    if focus is not None and focus.phase == "break":
        focus = focus.suspended_focus
    with _pomodoro_transaction() as connection:
        if focus is not None and focus.mode == "Pomodoro" and focus.phase == "focus":
            elapsed = focus.total_seconds - focus.remaining_seconds
            if elapsed > 0 and _claim_completion(connection, focus):
                connection.execute(
                    "INSERT INTO study_sessions (subject, duration_seconds, recorded_at) VALUES (?, ?, ?)",
                    (focus.subject, elapsed, datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()),
                )
                if focus.remaining_seconds == 0:
                    _award_focus(connection, focus.subject)
                else:
                    _add_focus_progress(connection, focus.subject, elapsed)
        connection.execute("DELETE FROM active_timer")
        return connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()


def _claim_completion(connection, timer):
    if timer is None:
        return True
    return connection.execute("INSERT OR IGNORE INTO timer_completions VALUES (?)",
                              (timer.session_id,)).rowcount == 1


def _create_session_table(connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY,
            subject TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
            recorded_at TEXT NOT NULL
        )
    """)


@contextmanager
def _pomodoro_transaction():
    config.DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(config.DATABASE_PATH)) as connection:
        with connection:
            # Serialize read/modify/write operations, including across app instances.
            connection.execute("BEGIN IMMEDIATE")
            _create_session_table(connection)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS pomodoro_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance_seconds INTEGER NOT NULL CHECK (balance_seconds >= 0),
                    cycle_position INTEGER NOT NULL CHECK (cycle_position >= 0)
                )
            """)
            connection.execute("INSERT OR IGNORE INTO pomodoro_state VALUES (1, 0, 0)")
            connection.execute("""CREATE TABLE IF NOT EXISTS subject_focus_progress (
                subject TEXT PRIMARY KEY,
                elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0)
            )""")
            _create_progress_tables(connection)
            _migrate_active_timer(connection)
            _migrate_shared_focus(connection)
            connection.execute("""CREATE TABLE IF NOT EXISTS pomodoro_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                focus_scope TEXT NOT NULL CHECK (focus_scope IN ('shared', 'per_subject'))
            )""")
            connection.execute("INSERT OR IGNORE INTO pomodoro_settings VALUES (1, 'shared')")
            # Legacy subject_focus_progress remains an archive, never imported here.
            connection.execute("""CREATE TABLE IF NOT EXISTS per_subject_focus_progress (
                subject TEXT PRIMARY KEY,
                elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0)
            )""")
            yield connection


def get_pomodoro_state() -> Tuple[int, int]:
    """Return persistent (break balance in seconds, completed focuses in cycle)."""
    with _pomodoro_transaction() as connection:
        return connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()


def _get_focus_scope(connection):
    scope = connection.execute("SELECT focus_scope FROM pomodoro_settings WHERE id = 1").fetchone()[0]
    if scope not in FOCUS_SCOPES:
        raise sqlite3.DatabaseError("Invalid Pomodoro progress setting")
    return scope


def get_focus_scope() -> str:
    with _pomodoro_transaction() as connection:
        return _get_focus_scope(connection)


def set_focus_scope(scope: str, subject: str) -> int:
    """Save the idle preference and return its target progress atomically."""
    if scope not in FOCUS_SCOPES:
        raise ValueError("Unknown Pomodoro progress setting")
    with _pomodoro_transaction() as connection:
        if connection.execute("SELECT 1 FROM active_timer WHERE phase != 'done'").fetchone():
            raise ValueError("Reset or finish the timer before changing Settings.")
        connection.execute("UPDATE pomodoro_settings SET focus_scope = ? WHERE id = 1", (scope,))
        return _get_focus_progress(connection, subject)


def _get_focus_progress(connection, subject):
    if _get_focus_scope(connection) == "shared":
        row = connection.execute(
            "SELECT elapsed_seconds FROM shared_focus_progress WHERE id = 1"
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT elapsed_seconds FROM per_subject_focus_progress WHERE subject = ?", (subject,)
        ).fetchone()
    seconds = row[0] if row else 0
    if type(seconds) is not int or not 0 <= seconds < config.POMODORO_FOCUS_SECONDS:
        raise sqlite3.DatabaseError("Invalid accumulated focus progress")
    return seconds


def get_focus_progress(subject: str = "Umum") -> int:
    """Read the chosen scope's target; the other scope remains untouched."""
    with _pomodoro_transaction() as connection:
        return _get_focus_progress(connection, subject)


def _add_focus_progress(connection, subject, elapsed):
    if _get_focus_scope(connection) == "shared":
        connection.execute("""UPDATE shared_focus_progress
            SET elapsed_seconds = elapsed_seconds + ? WHERE id = 1""", (elapsed,))
    else:
        connection.execute("""INSERT INTO per_subject_focus_progress VALUES (?, ?)
            ON CONFLICT(subject) DO UPDATE SET elapsed_seconds = elapsed_seconds + excluded.elapsed_seconds""",
            (subject, elapsed))


def _award_focus(connection, subject):
    balance, position = connection.execute(
        "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
    ).fetchone()
    position = (position + 1) % config.POMODORO_TOTAL_SESSIONS
    reward = (config.POMODORO_LONG_BREAK_SECONDS if position == 0
              else config.POMODORO_SHORT_BREAK_SECONDS)
    balance += reward
    connection.execute(
        "UPDATE pomodoro_state SET balance_seconds = ?, cycle_position = ? WHERE id = 1",
        (balance, position),
    )
    if _get_focus_scope(connection) == "shared":
        connection.execute("UPDATE shared_focus_progress SET elapsed_seconds = 0 WHERE id = 1")
    else:
        connection.execute("DELETE FROM per_subject_focus_progress WHERE subject = ?", (subject,))
    return balance, position


def complete_pomodoro_focus(subject: str, total_seconds: int, timer=None) -> Tuple[int, int]:
    """Atomically save a completed focus and award its break entitlement."""
    recorded_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with _pomodoro_transaction() as connection:
        balance, position = connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()
        if not _claim_completion(connection, timer):
            return balance, position
        connection.execute(
            "INSERT INTO study_sessions (subject, duration_seconds, recorded_at) VALUES (?, ?, ?)",
            (subject, total_seconds, recorded_at),
        )
        balance, position = _award_focus(connection, subject)
        if timer is not None:
            _write_active_timer(connection, replace(timer, phase="choice", remaining_seconds=0))
        return balance, position


def consume_break_second(timer=None) -> Tuple[int, int]:
    """Commit one elapsed break second; never allow a negative balance."""
    with _pomodoro_transaction() as connection:
        cursor = connection.execute(
            "UPDATE pomodoro_state SET balance_seconds = balance_seconds - 1 "
            "WHERE id = 1 AND balance_seconds > 0"
        )
        if cursor.rowcount != 1:
            raise ValueError("No break balance remaining")
        if timer is not None:
            _write_active_timer(connection, timer)
        return connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()


def save_session(subject: str, total_seconds: int, timer=None) -> None:
    recorded_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with _pomodoro_transaction() as connection:
        if not _claim_completion(connection, timer):
            return
        connection.execute(
            "INSERT INTO study_sessions (subject, duration_seconds, recorded_at) VALUES (?, ?, ?)",
            (subject, total_seconds, recorded_at),
        )
        if timer is not None:
            _write_active_timer(connection, replace(timer, phase="done", remaining_seconds=0))


def get_recent_sessions(limit: int = 20) -> List[Tuple[str, int, str]]:
    """Return recent sessions as (subject, duration_seconds, recorded_at)."""
    if not config.DATABASE_PATH.exists():
        return []

    with closing(sqlite3.connect(config.DATABASE_PATH)) as connection:
        cursor = connection.execute(
            """
            SELECT subject, duration_seconds, recorded_at
            FROM study_sessions
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cursor.fetchall()


def get_summary_by_subject() -> List[Tuple[str, int, int]]:
    """Return summary as (subject, total_seconds, session_count) ordered by total desc."""
    if not config.DATABASE_PATH.exists():
        return []

    with closing(sqlite3.connect(config.DATABASE_PATH)) as connection:
        cursor = connection.execute(
            """
            SELECT subject, SUM(duration_seconds) as total, COUNT(*) as count
            FROM study_sessions
            GROUP BY subject
            ORDER BY total DESC
            """
        )
        return cursor.fetchall()
