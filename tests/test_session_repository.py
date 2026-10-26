from datetime import datetime, timedelta
import sqlite3

import config
import session_repository


def test_save_session_creates_database_and_stores_session(tmp_path, monkeypatch):
    data_directory = tmp_path / "StudyTimer"
    database_path = data_directory / "study_sessions.sqlite3"
    monkeypatch.setattr(config, "DATA_DIRECTORY", data_directory)
    monkeypatch.setattr(config, "DATABASE_PATH", database_path)

    session_repository.save_session("English", 1500)

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT subject, duration_seconds, recorded_at FROM study_sessions"
        ).fetchone()

    assert row is not None
    assert row[0:2] == ("English", 1500)
    assert datetime.fromisoformat(row[2]).utcoffset() == timedelta(hours=7)


def test_save_session_propagates_database_errors(tmp_path, monkeypatch):
    data_directory = tmp_path / "not-a-directory"
    data_directory.touch()
    monkeypatch.setattr(config, "DATA_DIRECTORY", data_directory)

    try:
        session_repository.save_session("English", 1500)
    except OSError:
        pass
    else:
        raise AssertionError("Expected the invalid database directory to fail")


def test_get_recent_sessions_returns_empty_when_no_db(tmp_path, monkeypatch):
    database_path = tmp_path / "nonexistent.sqlite3"
    monkeypatch.setattr(config, "DATABASE_PATH", database_path)

    result = session_repository.get_recent_sessions()
    assert result == []


def test_get_recent_sessions_returns_ordered_sessions(tmp_path, monkeypatch):
    data_directory = tmp_path / "StudyTimer"
    database_path = data_directory / "study_sessions.sqlite3"
    monkeypatch.setattr(config, "DATA_DIRECTORY", data_directory)
    monkeypatch.setattr(config, "DATABASE_PATH", database_path)

    session_repository.save_session("English", 900)
    session_repository.save_session("Programming", 1800)
    session_repository.save_session("Linux", 600)

    result = session_repository.get_recent_sessions(limit=2)
    assert len(result) == 2
    assert result[0][0] == "Linux"
    assert result[1][0] == "Programming"


def test_get_summary_by_subject_aggregates_correctly(tmp_path, monkeypatch):
    data_directory = tmp_path / "StudyTimer"
    database_path = data_directory / "study_sessions.sqlite3"
    monkeypatch.setattr(config, "DATA_DIRECTORY", data_directory)
    monkeypatch.setattr(config, "DATABASE_PATH", database_path)

    session_repository.save_session("English", 900)
    session_repository.save_session("English", 600)
    session_repository.save_session("Programming", 1800)

    result = session_repository.get_summary_by_subject()
    assert len(result) == 2

    prog = next(r for r in result if r[0] == "Programming")
    eng = next(r for r in result if r[0] == "English")

    assert prog[1] == 1800
    assert prog[2] == 1
    assert eng[1] == 1500
    assert eng[2] == 2
