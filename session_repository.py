import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from typing import List, Tuple

import config
from zoneinfo import ZoneInfo


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
            yield connection


def get_pomodoro_state() -> Tuple[int, int]:
    """Return persistent (break balance in seconds, completed focuses in cycle)."""
    with _pomodoro_transaction() as connection:
        return connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()


def complete_pomodoro_focus(subject: str, total_seconds: int) -> Tuple[int, int]:
    """Atomically save a completed focus and award its break entitlement."""
    recorded_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    with _pomodoro_transaction() as connection:
        balance, position = connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()
        position = (position + 1) % config.POMODORO_TOTAL_SESSIONS
        reward = (config.POMODORO_LONG_BREAK_MINUTES if position == 0
                  else config.POMODORO_SHORT_BREAK_MINUTES) * 60
        connection.execute(
            "INSERT INTO study_sessions (subject, duration_seconds, recorded_at) VALUES (?, ?, ?)",
            (subject, total_seconds, recorded_at),
        )
        balance += reward
        connection.execute(
            "UPDATE pomodoro_state SET balance_seconds = ?, cycle_position = ? WHERE id = 1",
            (balance, position),
        )
        return balance, position


def consume_break_second() -> Tuple[int, int]:
    """Commit one elapsed break second; never allow a negative balance."""
    with _pomodoro_transaction() as connection:
        cursor = connection.execute(
            "UPDATE pomodoro_state SET balance_seconds = balance_seconds - 1 "
            "WHERE id = 1 AND balance_seconds > 0"
        )
        if cursor.rowcount != 1:
            raise ValueError("No break balance remaining")
        return connection.execute(
            "SELECT balance_seconds, cycle_position FROM pomodoro_state WHERE id = 1"
        ).fetchone()


def save_session(subject: str, total_seconds: int) -> None:
    recorded_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    config.DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(config.DATABASE_PATH)) as connection:
        with connection:
            _create_session_table(connection)
            connection.execute(
                """
                INSERT INTO study_sessions (subject, duration_seconds, recorded_at)
                VALUES (?, ?, ?)
                """,
                (subject, total_seconds, recorded_at),
            )


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
