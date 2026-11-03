"""SQLite schema setup and migrations, using the caller's transaction."""

import json
import sqlite3

from study_timer import config
from study_timer.models import ActiveTimer


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


def _create_session_table(connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY,
            subject TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
            recorded_at TEXT NOT NULL
        )
    """)


def ensure_schema(connection):
    """Preserve migration order without opening or committing a connection."""
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
        focus_scope TEXT NOT NULL CHECK (focus_scope IN ('shared', 'per_subject')),
        tick_sound INTEGER NOT NULL DEFAULT 0 CHECK (tick_sound IN (0, 1))
    )""")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(pomodoro_settings)")}
    if "tick_sound" not in columns:
        connection.execute("ALTER TABLE pomodoro_settings ADD COLUMN tick_sound INTEGER NOT NULL DEFAULT 0 CHECK (tick_sound IN (0, 1))")
    if "tick_volume" not in columns:
        connection.execute("ALTER TABLE pomodoro_settings ADD COLUMN tick_volume INTEGER NOT NULL DEFAULT 100 CHECK (tick_volume BETWEEN 0 AND 100)")
    if "tick_volume_percent" not in columns:
        # Keep the old constrained column and migrate without rebuilding the table.
        connection.execute("ALTER TABLE pomodoro_settings ADD COLUMN tick_volume_percent INTEGER NOT NULL DEFAULT 100 CHECK (tick_volume_percent BETWEEN 0 AND 400)")
        connection.execute("UPDATE pomodoro_settings SET tick_volume_percent = tick_volume")
    connection.execute("INSERT OR IGNORE INTO pomodoro_settings (id, focus_scope) VALUES (1, 'shared')")
    # Legacy subject_focus_progress remains an archive, never imported here.
    connection.execute("""CREATE TABLE IF NOT EXISTS per_subject_focus_progress (
        subject TEXT PRIMARY KEY,
        elapsed_seconds INTEGER NOT NULL CHECK (elapsed_seconds >= 0)
    )""")
