import sqlite3
from dataclasses import dataclass, replace
from contextlib import closing, contextmanager
from datetime import datetime
from typing import List, Tuple

import config
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ActiveTimer:
    session_id: str
    mode: str
    subject: str
    phase: str
    total_seconds: int
    remaining_seconds: int
    return_to_choice: bool = False


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


def _write_active_timer(connection, timer):
    connection.execute("""INSERT OR REPLACE INTO active_timer
        VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (timer.session_id, timer.mode, timer.subject, timer.phase,
         timer.total_seconds, timer.remaining_seconds, int(timer.return_to_choice)))


def load_active_timer():
    with _pomodoro_transaction() as connection:
        row = connection.execute("""SELECT session_id, mode, subject, phase,
            total_seconds, remaining_seconds, return_to_choice FROM active_timer WHERE id = 1""").fetchone()
        if row is None:
            return None
        timer = ActiveTimer(*row[:-1], bool(row[-1]))
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
            _create_progress_tables(connection)
            yield connection


def get_pomodoro_state() -> Tuple[int, int]:
    """Return persistent (break balance in seconds, completed focuses in cycle)."""
    with _pomodoro_transaction() as connection:
        return connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()


def complete_pomodoro_focus(subject: str, total_seconds: int, timer=None) -> Tuple[int, int]:
    """Atomically save a completed focus and award its break entitlement."""
    recorded_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with _pomodoro_transaction() as connection:
        balance, position = connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()
        if not _claim_completion(connection, timer):
            return balance, position
        position = (position + 1) % config.POMODORO_TOTAL_SESSIONS
        reward = (config.POMODORO_LONG_BREAK_SECONDS if position == 0
                  else config.POMODORO_SHORT_BREAK_SECONDS)
        connection.execute(
            "INSERT INTO study_sessions (subject, duration_seconds, recorded_at) VALUES (?, ?, ?)",
            (subject, total_seconds, recorded_at),
        )
        balance += reward
        connection.execute(
            "UPDATE pomodoro_state SET balance_seconds = ?, cycle_position = ? WHERE id = 1",
            (balance, position),
        )
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
