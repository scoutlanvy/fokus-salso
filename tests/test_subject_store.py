import pytest

import config
import subject_store


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
