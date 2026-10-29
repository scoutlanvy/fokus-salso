"""Persistent subject choices, separate from session history."""

import json
import os
import tempfile

import config


def load_subjects():
    path = config.DATA_DIRECTORY / "subjects.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        saved = []
    legacy = isinstance(saved, list)
    if not legacy:
        if not isinstance(saved, dict) or saved.get("version") != 1:
            raise ValueError("Invalid saved subject list")
        saved = saved.get("subjects")
    if not isinstance(saved, list) or any(
        not isinstance(name, str) or not name.strip() for name in saved
    ):
        raise ValueError("Invalid saved subject list")
    subjects = list(config.SUBJECT_OPTIONS) if legacy else ["Umum"]
    for name in saved:
        name = name.strip()
        if not any(existing.casefold() == name.casefold() for existing in subjects):
            subjects.append(name)
    return subjects


def add_subject(name):
    name = name.strip()
    if not name:
        raise ValueError("Enter a subject name.")
    subjects = load_subjects()
    for existing in subjects:
        if existing.casefold() == name.casefold():
            return subjects, existing
    subjects.append(name)
    _save_subjects(subjects)
    return subjects, name


def delete_subject(name):
    subjects = load_subjects()
    if name.casefold() == "umum":
        raise ValueError("Umum cannot be deleted.")
    remaining = [subject for subject in subjects if subject.casefold() != name.casefold()]
    if remaining == subjects:
        raise ValueError("Subject not found.")
    _save_subjects(remaining)
    return remaining


def _save_subjects(subjects):
    config.DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config.DATA_DIRECTORY,
            prefix="subjects-", suffix=".tmp", delete=False,
        ) as output:
            temporary = output.name
            json.dump({"version": 1, "subjects": subjects}, output, ensure_ascii=False, indent=2)
        os.replace(temporary, config.DATA_DIRECTORY / "subjects.json")
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
