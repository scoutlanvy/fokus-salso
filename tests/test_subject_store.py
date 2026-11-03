import pytest
import json

from study_timer import config
from study_timer import subject_store


def test_subjects_persist_and_duplicates_select_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    subjects, selected = subject_store.add_subject("  Matematika  ")
    assert selected == "Matematika"
    assert subject_store.load_subjects() == subjects
    assert subject_store.add_subject("matematika") == (subjects, "Matematika")
    assert subject_store.add_subject("UMUM") == (subjects, "Umum")
    with pytest.raises(ValueError):
        subject_store.add_subject("  ")
    assert subject_store.load_subjects() == subjects
    assert not (tmp_path / "study_sessions.sqlite3").exists()


def test_failed_save_preserves_previous_list(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    subject_store.add_subject("Matematika")
    original = (tmp_path / "subjects.json").read_bytes()

    def fail(*args):
        raise OSError("Cannot replace file")

    monkeypatch.setattr(subject_store.os, "replace", fail)
    with pytest.raises(OSError):
        subject_store.add_subject("Fisika")
    assert (tmp_path / "subjects.json").read_bytes() == original
    assert list(tmp_path.iterdir()) == [tmp_path / "subjects.json"]


def test_invalid_saved_list_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    path = tmp_path / "subjects.json"
    path.write_text('{"invalid": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        subject_store.add_subject("Fisika")
    assert path.read_text(encoding="utf-8") == '{"invalid": true}'


def test_delete_defaults_custom_and_readd_preserves_database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    database = tmp_path / "study_sessions.sqlite3"
    database.write_bytes(b"untouched history and progress")
    subject_store.add_subject("Matematika")
    for name in ("English", "Matematika"):
        remaining = subject_store.delete_subject(name)
        assert name not in remaining
        assert subject_store.load_subjects() == remaining
    assert "Anki" in remaining
    with pytest.raises(ValueError):
        subject_store.delete_subject("UMUM")
    with pytest.raises(ValueError):
        subject_store.delete_subject("Missing")
    assert subject_store.add_subject("English")[1] == "English"
    assert database.read_bytes() == b"untouched history and progress"


def test_legacy_list_migrates_on_delete_and_failed_delete_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    path = tmp_path / "subjects.json"
    path.write_text('["Custom", "english"]', encoding="utf-8")
    assert subject_store.load_subjects() == config.SUBJECT_OPTIONS + ["Custom"]
    subject_store.delete_subject("English")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"version": 1, "subjects": subject_store.load_subjects()}
    original = path.read_bytes()

    def fail(*args):
        raise OSError("Cannot replace file")

    monkeypatch.setattr(subject_store.os, "replace", fail)
    with pytest.raises(OSError):
        subject_store.delete_subject("Custom")
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
