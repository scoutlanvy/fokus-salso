import sqlite3
from contextlib import closing
from datetime import datetime
from typing import List, Tuple

import config
from zoneinfo import ZoneInfo


def save_session(subject: str, total_seconds: int) -> None:
    recorded_at = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
    config.DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(config.DATABASE_PATH)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS study_sessions (
                    id INTEGER PRIMARY KEY,
                    subject TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
                    recorded_at TEXT NOT NULL
                )
                """
            )
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
