import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import customtkinter as ctk
import pytest

import config
import gui
from instance_lock import AlreadyRunningError, InstanceLock
import session_repository as repository
import timer_service
from timer_service import TimerService


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *_: None)


def snapshot(phase="focus", remaining=1492, total=1500, return_to_choice=True):
    return repository.ActiveTimer(str(uuid4()), "Manual" if phase == "manual" else "Pomodoro",
                                  "English", phase, total, remaining, return_to_choice)


def service():
    return TimerService(lambda _: None, lambda _: None, lambda *_, **__: None)


def test_settings_keep_independent_targets_and_persist_across_restart():
    timer = service()
    assert timer.focus_scope == "shared"
    repository.reset_active_timer(replace(snapshot(remaining=1080), subject="Umum"))
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("INSERT INTO subject_focus_progress VALUES ('Anki', 900)")
    assert timer.change_focus_scope("per_subject", "Anki") == 1500
    assert service().focus_scope == "per_subject"
    repository.reset_active_timer(replace(snapshot(remaining=1320), subject="Anki"))
    repository.reset_active_timer(replace(snapshot(remaining=1200), subject="Umum"))
    assert timer.focus_seconds_remaining("Anki") == 1320
    assert timer.focus_seconds_remaining("Umum") == 1200
    assert timer.change_focus_scope("shared", "Anki") == 1080
    assert timer.focus_seconds_remaining("Umum") == 1080
    assert timer.change_focus_scope("per_subject", "Anki") == 1320
    final_segment = replace(snapshot(remaining=0, total=1320), subject="Anki")
    repository.reset_active_timer(final_segment)
    repository.reset_active_timer(final_segment)
    assert timer.focus_seconds_remaining("Anki") == 1500
    assert timer.focus_seconds_remaining("Umum") == 1200
    assert repository.get_pomodoro_state() == (300, 1)
    assert repository.get_summary_by_subject() == [("Anki", 1500, 2), ("Umum", 720, 2)]
    assert timer.change_focus_scope("shared", "Anki") == 1080
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        assert connection.execute("SELECT * FROM subject_focus_progress").fetchall() == [("Anki", 900)]


@pytest.mark.parametrize("phase", ["manual", "focus", "break", "choice"])
def test_settings_reject_unfinished_checkpoint_even_before_restore(phase):
    repository.save_active_timer(snapshot(phase, remaining=0 if phase == "choice" else 10))
    timer = service()
    with pytest.raises(ValueError):
        timer.change_focus_scope("per_subject", "English")
    assert timer.focus_scope == repository.get_focus_scope() == "shared"
    assert repository.load_active_timer().phase == phase


def test_settings_save_and_target_read_failures_are_atomic():
    timer = service()
    repository.reset_active_timer(snapshot(remaining=1080))
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TRIGGER fail_settings BEFORE UPDATE ON pomodoro_settings
            BEGIN SELECT RAISE(ABORT, 'disk full'); END""")
    with pytest.raises(sqlite3.DatabaseError):
        timer.change_focus_scope("per_subject", "English")
    assert timer.focus_scope == repository.get_focus_scope() == "shared"
    assert timer.focus_seconds_remaining("English") == 1080
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("DROP TRIGGER fail_settings")
        connection.execute("INSERT INTO per_subject_focus_progress VALUES ('English', 1500)")
    with pytest.raises(sqlite3.DatabaseError):
        timer.change_focus_scope("per_subject", "English")
    assert timer.focus_scope == repository.get_focus_scope() == "shared"
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("UPDATE per_subject_focus_progress SET elapsed_seconds = 100")
    assert timer.change_focus_scope("per_subject", "English") == 1400
    assert repository.get_summary_by_subject() == [("English", 420, 1)]


@pytest.mark.parametrize("scope", ["shared", "per_subject"])
def test_settings_scope_survives_short_focus_recovery_and_completion(scope, monkeypatch):
    timer = service()
    timer.change_focus_scope(scope, "English")
    repository.reset_active_timer(snapshot(remaining=607))
    saved = snapshot(remaining=1, total=607)
    repository.save_active_timer(saved)
    monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 30))
    try:
        assert timer.restore_progress() == saved
        assert not timer.can_change_settings()
        with pytest.raises(ValueError):
            timer.change_focus_scope("per_subject" if scope == "shared" else "shared", "English")
        assert timer.suspend_for_close()
        timer = service()
        assert timer.focus_scope == scope
        assert timer.restore_progress() == saved
        timer.resume_timer()
        wait_for(lambda: timer.is_alarm_active)
        assert not timer.can_change_settings()
        assert repository.get_summary_by_subject() == [("English", 1500, 2)]
        assert repository.get_focus_progress("English") == 0
        assert repository.get_pomodoro_state() == (300, 1)
        timer.stop_alarm()
        wait_for(lambda: timer.current_phase == "choice")
        assert not timer.can_change_settings()
    finally:
        timer.reset_timer()


def test_settings_preview_isolation(tmp_path, monkeypatch):
    timer = service()
    timer.change_focus_scope("per_subject", "English")
    repository.reset_active_timer(snapshot(remaining=1080))
    normal_path = config.DATABASE_PATH
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "preview.sqlite3")
    monkeypatch.setattr(config, "POMODORO_FOCUS_SECONDS", 10)
    preview = service()
    assert preview.focus_scope == "shared"
    repository.reset_active_timer(snapshot(remaining=6, total=10))
    assert preview.change_focus_scope("per_subject", "English") == 10
    assert preview.change_focus_scope("shared", "English") == 6
    monkeypatch.setattr(config, "DATABASE_PATH", normal_path)
    monkeypatch.setattr(config, "POMODORO_FOCUS_SECONDS", 1500)
    assert service().focus_scope == "per_subject"
    assert repository.get_focus_progress("English") == 420


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("Timed out waiting for state")


@pytest.mark.parametrize("phase,remaining,total,return_to_choice", [
    ("manual", 73, 100, False), ("focus", 1492, 1500, True),
    ("break", 2, 10, True), ("break", 2, 10, False),
])
def test_restore_is_paused_and_close_preserves_exact_progress(phase, remaining, total, return_to_choice):
    saved = snapshot(phase, remaining, total, return_to_choice)
    repository.save_active_timer(saved)
    timer = service()
    try:
        assert timer.restore_progress() == saved
        wait_for(lambda: timer.current_phase == phase)
        assert timer.pause_event.is_set()
        threading.Event().wait(0.15)
        assert timer.remaining_seconds == remaining
        assert timer.is_running
        assert timer.suspend_for_close()
        assert not timer.timer_thread.is_alive()
        assert repository.load_active_timer() == saved
        assert repository.get_recent_sessions() == []
    finally:
        timer.reset_timer()


def test_manual_resume_records_original_duration_once(monkeypatch):
    saved = snapshot("manual", 1, 100, False)
    repository.save_active_timer(saved)
    monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 30))
    timer = service()
    try:
        timer.restore_progress()
        wait_for(lambda: timer.current_phase == "manual")
        timer.resume_timer()
        wait_for(lambda: timer.is_alarm_active)
        assert repository.get_recent_sessions()[0][:2] == ("English", 100)
        assert repository.get_pomodoro_state() == (0, 0)
        assert timer.suspend_for_close()
        reopened = service()
        assert reopened.restore_progress() is None
        assert not reopened.is_running
        assert len(repository.get_recent_sessions()) == 1
    finally:
        timer.reset_timer()


@pytest.mark.parametrize("return_to_choice", [False, True])
def test_resumed_break_debits_only_remaining_seconds(monkeypatch, return_to_choice):
    repository.complete_pomodoro_focus("Umum", 1500)
    repository.save_active_timer(snapshot("break", 1, 10, return_to_choice))
    monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 30))
    timer = service()
    try:
        timer.restore_progress()
        timer.resume_timer()
        wait_for(lambda: timer.is_alarm_active)
        assert repository.get_pomodoro_state() == (299, 1)
        timer.stop_alarm()
        wait_for(lambda: timer.current_phase == "choice" if return_to_choice else not timer.is_running)
        assert repository.load_active_timer().phase == ("choice" if return_to_choice else "done")
    finally:
        timer.reset_timer()


@pytest.mark.parametrize("phase", ["manual", "focus"])
def test_completion_is_atomic_and_idempotent(phase):
    saved = snapshot(phase, 0, 100, phase == "focus")
    repository.save_active_timer(saved)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TRIGGER fail_progress BEFORE INSERT ON active_timer
            BEGIN SELECT RAISE(ABORT, 'disk failure'); END""")
    complete = repository.save_session if phase == "manual" else repository.complete_pomodoro_focus
    with pytest.raises(sqlite3.DatabaseError):
        complete(saved.subject, saved.total_seconds, saved)
    assert repository.get_recent_sessions() == []
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.load_active_timer() == saved
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("DROP TRIGGER fail_progress")
    complete(saved.subject, saved.total_seconds, saved)
    complete(saved.subject, saved.total_seconds, saved)
    assert len(repository.get_recent_sessions()) == 1
    assert repository.get_pomodoro_state() == ((300, 1) if phase == "focus" else (0, 0))
    assert repository.load_active_timer().phase == ("choice" if phase == "focus" else "done")


def test_break_tick_rolls_back_balance_and_progress_together():
    repository.complete_pomodoro_focus("Umum", 1500)
    saved = snapshot("break", 2, 10)
    repository.save_active_timer(saved)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TRIGGER fail_progress BEFORE INSERT ON active_timer
            BEGIN SELECT RAISE(ABORT, 'disk failure'); END""")
    with pytest.raises(sqlite3.DatabaseError):
        repository.consume_break_second(replace(saved, remaining_seconds=1))
    assert repository.get_pomodoro_state() == (300, 1)
    assert repository.load_active_timer() == saved


def test_failed_tick_pauses_before_advancing_and_resume_retries(monkeypatch):
    saved = snapshot("focus", 2, 1500)
    repository.save_active_timer(saved)
    timer = service()
    original = timer_service.save_active_timer
    calls = []

    def fail_once(progress):
        calls.append(progress)
        if len(calls) == 1:
            raise sqlite3.OperationalError("disk full")
        return original(progress)

    monkeypatch.setattr(timer_service, "save_active_timer", fail_once)
    monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 30))
    try:
        timer.restore_progress()
        timer.resume_timer()
        wait_for(lambda: len(calls) == 1 and timer.pause_event.is_set())
        assert timer.remaining_seconds == 2
        assert repository.load_active_timer() == saved
        timer.resume_timer()
        wait_for(lambda: timer.is_alarm_active)
        assert len(repository.get_recent_sessions()) == 1
        assert repository.get_pomodoro_state() == (300, 1)
    finally:
        timer.reset_timer()


def test_failed_close_keeps_timer_paused_and_retry_can_close(monkeypatch):
    saved = snapshot()
    repository.save_active_timer(saved)
    timer = service()
    try:
        timer.restore_progress()
        original = timer_service.save_active_timer
        monkeypatch.setattr(timer_service, "save_active_timer",
                            lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
        assert not timer.suspend_for_close()
        assert timer.pause_event.is_set()
        assert not timer.stop_event.is_set()
        assert repository.load_active_timer() == saved
        monkeypatch.setattr(timer_service, "save_active_timer", original)
        assert timer.suspend_for_close()
        assert repository.load_active_timer() == saved
    finally:
        timer.reset_timer()


def test_failed_restore_blocks_start_and_reset_without_overwriting(monkeypatch):
    saved = snapshot()
    repository.save_active_timer(saved)
    timer = service()
    monkeypatch.setattr(timer_service, "load_active_timer",
                        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("read failure")))
    assert timer.restore_progress() is None
    timer.start_pomodoro("Umum")
    timer.start_timer(10, "Umum")
    assert not timer.start_break(1)
    assert not timer.reset_timer()
    assert not timer.is_running
    assert timer.suspend_for_close()
    assert repository.load_active_timer() == saved


@pytest.mark.parametrize("phase,remaining,return_to_choice,expected", [
    ("focus", 1492, True, "Resume"), ("manual", 73, False, "Resume"),
    ("break", 10, True, "Resume"), ("choice", 0, True, "Continue Focus"),
    ("break", 0, True, "Continue Focus"), ("done", 0, False, "Start"),
])
def test_gui_restores_controls_and_reset(phase, remaining, return_to_choice, expected, tmp_path):
    repository.complete_pomodoro_focus("Umum", 1500)
    saved = snapshot(phase, remaining, 1500, return_to_choice)
    repository.save_active_timer(saved)
    script = """
import customtkinter as ctk
import gui
import session_repository as repository
from timer_service import TimerService
saved = repository.load_active_timer()
expected = 'Start' if saved.phase == 'done' else (
    'Continue Focus' if saved.phase == 'choice' or (saved.phase == 'break' and not saved.remaining_seconds)
    else 'Resume')
def inspect(app):
    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)
    try:
        deadline = time.monotonic() + 3
        while True:
            app.update()
            widgets = list(descendants(app))
            buttons = [w for w in widgets if isinstance(w, ctk.CTkButton)
                       and w.cget('text') == expected and w.cget('state') == 'normal']
            if buttons:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        mode = next(w for w in widgets if isinstance(w, ctk.CTkOptionMenu) and 'Pomodoro' in w.cget('values'))
        subject = next(w for w in widgets if isinstance(w, ctk.CTkOptionMenu) and 'English' in w.cget('values'))
        choose = next(w for w in widgets if isinstance(w, ctk.CTkButton) and w.cget('text') == 'Choose Duration')
        assert choose.cget('state') == ('disabled' if saved.phase == 'manual' or (
            saved.phase == 'break' and saved.remaining_seconds > 0) else 'normal')
        if saved.phase != 'done':
            assert mode.get() == saved.mode
            assert subject.get() == saved.subject
            assert mode.cget('state') == 'disabled'
            assert any(isinstance(w, ctk.CTkLabel) and str(w.cget('textvariable'))
                       and app.getvar(str(w.cget('textvariable'))) == TimerService.format_hms(None, saved.remaining_seconds)
                       for w in widgets)
        reset = next(w for w in widgets if isinstance(w, ctk.CTkButton) and w.cget('text') == 'Reset')
        selected_before_reset = subject.get()
        reset.invoke()
        app.update()
        assert repository.load_active_timer() is None
        assert mode.cget('state') == 'normal'
        assert subject.get() == selected_before_reset
        if saved.phase == 'focus':
            assert ('English', saved.total_seconds - saved.remaining_seconds, 1) in repository.get_summary_by_subject()
            assert any(isinstance(w, ctk.CTkLabel) and w.cget('text') == '8s'
                       for w in descendants(app))
            assert any(isinstance(w, ctk.CTkLabel)
                       and w.cget('text') == 'Target progress: 00:00:08 / 00:25:00'
                       for w in descendants(app))
            assert any(isinstance(w, ctk.CTkLabel) and str(w.cget('textvariable'))
                       and app.getvar(str(w.cget('textvariable'))) == '00:24:52'
                       for w in descendants(app))
            subject.set('Umum')
            assert any(isinstance(w, ctk.CTkLabel) and str(w.cget('textvariable'))
                       and app.getvar(str(w.cget('textvariable'))) == '00:24:52'
                       for w in descendants(app))
            subject.set('English')
    finally:
        app.tk.call(app.protocol('WM_DELETE_WINDOW'))
ctk.CTk.mainloop = inspect
gui.run_app()
"""
    process = child_process(script, tmp_path)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stdout + stderr


def test_reset_retains_history_and_balance():
    repository.complete_pomodoro_focus("Umum", 1500)
    repository.save_active_timer(snapshot())
    timer = service()
    timer.restore_progress()
    assert timer.reset_timer()
    assert repository.load_active_timer() is None
    assert repository.get_pomodoro_state() == (300, 1)
    assert sorted(row[:2] for row in repository.get_recent_sessions()) == [("English", 8), ("Umum", 1500)]


@pytest.mark.parametrize("running", [False, True])
def test_reset_saves_recovered_focus_elapsed_once(running, monkeypatch):
    saved = snapshot("focus", 607)
    repository.save_active_timer(saved)
    timer = service()
    try:
        timer.restore_progress()
        wait_for(lambda: timer.current_phase == "focus")
        if running:
            monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 30))
            timer.resume_timer()
            wait_for(lambda: timer.remaining_seconds < 607)
        captured = []
        original_reset = timer_service.reset_active_timer

        def capture_reset(progress):
            if progress is not None:
                captured.append(progress.total_seconds - progress.remaining_seconds)
            original_reset(progress)

        monkeypatch.setattr(timer_service, "reset_active_timer", capture_reset)
        assert timer.reset_timer()
        elapsed = captured[0]
        assert repository.get_summary_by_subject() == [("English", elapsed, 1)]
        assert repository.get_pomodoro_state() == (0, 0)
        assert repository.load_active_timer() is None
        assert not timer.is_running
        assert not timer.timer_thread.is_alive()
        assert timer.reset_timer()
        assert repository.get_summary_by_subject() == [("English", elapsed, 1)]
        if not running:
            assert elapsed == 893
    finally:
        timer.suspend_for_close()


@pytest.mark.parametrize("phase,remaining", [("manual", 607), ("focus", 1500), ("break", 5)])
def test_reset_does_not_record_manual_zero_focus_or_break(phase, remaining):
    saved = snapshot(phase, remaining)
    repository.save_active_timer(saved)
    timer = service()
    timer.restore_progress()
    assert timer.reset_timer()
    assert repository.get_recent_sessions() == []
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.load_active_timer() is None


@pytest.mark.parametrize("remaining", [10, 0])
def test_reset_during_break_saves_only_suspended_focus(remaining):
    repository.complete_pomodoro_focus("Umum", 1500)
    focus = snapshot("focus", 607)
    saved = replace(snapshot("break", remaining, 20, False), suspended_focus=focus)
    repository.save_active_timer(saved)
    timer = service()
    timer.restore_progress()
    assert timer.reset_timer()
    assert sorted(row[:2] for row in repository.get_recent_sessions()) == [("English", 893), ("Umum", 1500)]
    assert repository.get_pomodoro_state() == (300, 1)
    assert repository.load_active_timer() is None


def test_reset_transaction_rolls_back_and_retry_does_not_duplicate():
    saved = snapshot("focus", 607)
    repository.save_active_timer(saved)
    timer = service()
    errors = []
    timer.on_storage_error = errors.append
    timer.restore_progress()
    try:
        with sqlite3.connect(config.DATABASE_PATH) as connection:
            connection.execute("""CREATE TRIGGER fail_reset BEFORE DELETE ON active_timer
                BEGIN SELECT RAISE(ABORT, 'disk failure'); END""")
        assert not timer.reset_timer()
        assert errors
        assert timer.pause_event.is_set()
        assert not timer.stop_event.is_set()
        assert repository.load_active_timer() == saved
        assert repository.get_recent_sessions() == []
        with sqlite3.connect(config.DATABASE_PATH) as connection:
            assert connection.execute("SELECT COUNT(*) FROM timer_completions").fetchone()[0] == 0
            connection.execute("DROP TRIGGER fail_reset")
        assert timer.reset_timer()
        repository.reset_active_timer(saved)  # Replaying the old UUID cannot add history.
        assert repository.get_summary_by_subject() == [("English", 893, 1)]
        assert repository.get_pomodoro_state() == (0, 0)
    finally:
        timer.suspend_for_close()


@pytest.mark.parametrize("phase", ["choice", "focus"])
def test_reset_cannot_duplicate_completed_focus_or_reward(phase):
    saved = snapshot("focus", 0)
    repository.complete_pomodoro_focus(saved.subject, saved.total_seconds, saved)
    repository.reset_active_timer(replace(saved, phase=phase))
    assert repository.get_summary_by_subject() == [("English", 1500, 1)]
    assert repository.get_pomodoro_state() == (300, 1)
    assert repository.load_active_timer() is None


def test_legacy_database_gains_progress_tables_without_changing_history():
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TABLE study_sessions (id INTEGER PRIMARY KEY,
            subject TEXT NOT NULL, duration_seconds INTEGER NOT NULL, recorded_at TEXT NOT NULL)""")
        connection.execute("INSERT INTO study_sessions VALUES (1, 'Anki', 60, '2026-01-01T12:00:00+07:00')")
    assert repository.load_active_timer() is None
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions() == [("Anki", 60, "2026-01-01T12:00:00+07:00")]
    assert repository.get_focus_progress() == 0


def test_accumulated_focus_multiple_resets_subjects_and_restart():
    first = snapshot("focus", 607)
    repository.reset_active_timer(first)
    repository.reset_active_timer(first)
    assert repository.get_focus_progress() == 893
    timer = service()
    try:
        assert timer.focus_seconds_remaining() == 607
        timer.start_pomodoro("English")
        wait_for(lambda: timer.current_phase == "focus")
        timer.pause_timer()
        assert timer._progress.total_seconds == 607
        assert timer.reset_timer()
        assert repository.get_focus_progress() == 893
        second = replace(first, session_id=str(uuid4()), total_seconds=607, remaining_seconds=400)
        repository.reset_active_timer(second)
        assert repository.get_focus_progress() == 1100
        assert service().focus_seconds_remaining() == 400
        assert repository.get_summary_by_subject() == [("English", 1100, 2)]
        assert repository.get_pomodoro_state() == (0, 0)
    finally:
        timer.suspend_for_close()


@pytest.mark.parametrize("umum", [None, 415, 727])
def test_shared_migration_uses_umum_once_and_preserves_legacy_data(umum):
    repository.save_session("Anki", 60)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("DROP TABLE shared_focus_progress")
        connection.execute("UPDATE pomodoro_state SET balance_seconds = 75, cycle_position = 2")
        connection.execute("INSERT INTO subject_focus_progress VALUES ('Anki', 120)")
        if umum is not None:
            connection.execute("INSERT INTO subject_focus_progress VALUES ('Umum', ?)", (umum,))
    assert repository.get_focus_progress() == (umum or 0)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        before = connection.execute("SELECT * FROM subject_focus_progress ORDER BY subject").fetchall()
        connection.execute("UPDATE shared_focus_progress SET elapsed_seconds = 800")
    assert repository.get_focus_progress() == 800
    assert repository.get_pomodoro_state() == (75, 2)
    assert repository.get_summary_by_subject() == [("Anki", 60, 1)]
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        assert connection.execute("SELECT * FROM subject_focus_progress ORDER BY subject").fetchall() == before
        assert connection.execute("SELECT migration_version FROM shared_focus_progress").fetchone() == (1,)


@pytest.mark.parametrize("suspended,remaining", [(False, 500), (True, 500), (False, 0)])
def test_shared_migration_preserves_legacy_active_focus(suspended, remaining):
    repository.save_session("English", 893)
    focus = snapshot("focus", remaining, 607)
    saved = replace(snapshot("break", 2, 10), suspended_focus=focus) if suspended else focus
    repository.save_active_timer(saved)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("DROP TABLE shared_focus_progress")
        connection.execute("INSERT INTO subject_focus_progress VALUES ('Umum', 415)")
        connection.execute("INSERT INTO subject_focus_progress VALUES ('English', 893)")
    assert repository.get_focus_progress() == 893
    assert repository.load_active_timer() == saved
    repository.reset_active_timer(saved)
    repository.reset_active_timer(saved)
    assert repository.get_focus_progress() == (1000 if remaining else 0)
    assert repository.get_summary_by_subject() == [("English", 1500 - remaining, 2)]
    assert repository.get_pomodoro_state() == ((0, 0) if remaining else (300, 1))


def test_shared_migration_failure_rolls_back_and_retries():
    repository.get_pomodoro_state()
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("DROP TABLE shared_focus_progress")
        connection.execute("INSERT INTO subject_focus_progress VALUES ('Umum', 1500)")
    with pytest.raises(sqlite3.DatabaseError):
        repository.get_focus_progress()
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("UPDATE subject_focus_progress SET elapsed_seconds = 415")
    assert repository.get_focus_progress() == 415


def test_shared_target_cross_subject_completion_and_duplicate_retry(monkeypatch):
    first = replace(snapshot("focus", 1080), subject="Umum")
    repository.reset_active_timer(first)
    repository.reset_active_timer(first)
    assert repository.get_focus_progress() == 420
    timer = service()

    def finish_segment(seconds, *args, **kwargs):
        assert seconds == 1080
        timer._checkpoint(replace(timer._progress, remaining_seconds=0))
        return True

    monkeypatch.setattr(timer, "_run_countdown", finish_segment)
    try:
        timer.start_pomodoro("Anki")
        wait_for(lambda: timer.is_alarm_active)
        repository.complete_pomodoro_focus("Anki", 1080, timer._progress)
        assert repository.get_summary_by_subject() == [("Anki", 1080, 1), ("Umum", 420, 1)]
        assert repository.get_focus_progress() == 0
        assert repository.get_pomodoro_state() == (300, 1)
        assert timer.focus_seconds_remaining() == 1500
    finally:
        timer.reset_timer()


def test_accumulated_remainder_completes_once_and_next_focus_is_full(monkeypatch):
    repository.reset_active_timer(snapshot("focus", 607))
    timer = service()
    observed = []

    def finish_segment(seconds, *args, **kwargs):
        observed.append(seconds)
        timer._checkpoint(replace(timer._progress, remaining_seconds=0))
        return True

    monkeypatch.setattr(timer, "_run_countdown", finish_segment)
    try:
        timer.start_pomodoro("English")
        wait_for(lambda: timer.is_alarm_active)
        assert observed == [607]
        assert repository.get_summary_by_subject() == [("English", 1500, 2)]
        assert repository.get_focus_progress() == 0
        assert repository.get_pomodoro_state() == (300, 1)
        timer.stop_alarm()
        wait_for(lambda: timer.current_phase == "choice")
        assert timer.continue_focus()
        wait_for(lambda: len(observed) == 2 and timer.is_alarm_active)
        assert observed == [607, 1500]
        assert repository.get_summary_by_subject() == [("English", 3000, 3)]
    finally:
        timer.reset_timer()


def test_accumulated_short_segment_recovers_without_counting_twice():
    repository.reset_active_timer(snapshot("focus", 607))
    segment = snapshot("focus", 500, 607)
    repository.save_active_timer(segment)
    timer = service()
    assert timer.restore_progress() == segment
    assert timer.focus_target_progress() == 1000
    assert timer.suspend_for_close()
    reopened = service()
    try:
        assert reopened.restore_progress() == segment
        assert reopened.reset_timer()
        assert repository.get_focus_progress() == 1000
        assert repository.get_summary_by_subject() == [("English", 1000, 2)]
        assert reopened.focus_seconds_remaining() == 500
    finally:
        reopened.suspend_for_close()


@pytest.mark.parametrize("scope", ["shared", "per_subject"])
def test_reset_at_zero_awards_target_once_and_rolls_back_on_failure(scope):
    repository.set_focus_scope(scope, "English")
    repository.reset_active_timer(snapshot("focus", 607))
    segment = snapshot("focus", 0, 607)
    repository.save_active_timer(segment)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TRIGGER fail_reset BEFORE DELETE ON active_timer
            BEGIN SELECT RAISE(ABORT, 'failure'); END""")
    with pytest.raises(sqlite3.DatabaseError):
        repository.reset_active_timer(segment)
    assert repository.get_focus_progress("English") == 893
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_summary_by_subject() == [("English", 893, 1)]
    assert repository.load_active_timer() == segment
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("DROP TRIGGER fail_reset")
    assert repository.reset_active_timer(segment) == (300, 1)
    assert repository.reset_active_timer(segment) == (300, 1)
    assert repository.get_focus_progress("English") == 0
    assert repository.get_summary_by_subject() == [("English", 1500, 2)]


def test_focus_read_failure_prevents_start_and_can_retry(monkeypatch):
    timer = service()
    original = timer_service.get_focus_progress

    def fail(_):
        raise sqlite3.OperationalError("cannot read progress")

    monkeypatch.setattr(timer_service, "get_focus_progress", fail)
    assert timer.focus_seconds_remaining() is None
    timer.start_pomodoro("English")
    assert not timer.is_running
    assert repository.load_active_timer() is None
    monkeypatch.setattr(timer_service, "get_focus_progress", original)
    try:
        timer.start_pomodoro("English")
        wait_for(lambda: timer.current_phase == "focus")
        assert timer._progress.total_seconds == 1500
    finally:
        timer.reset_timer()


def test_preview_accumulation_is_isolated(tmp_path, monkeypatch):
    repository.reset_active_timer(snapshot("focus", 607))
    normal_path = config.DATABASE_PATH
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "preview.sqlite3")
    monkeypatch.setattr(config, "POMODORO_FOCUS_SECONDS", 10)
    monkeypatch.setattr(config, "POMODORO_SHORT_BREAK_SECONDS", 5)
    repository.reset_active_timer(snapshot("focus", 6, 10))
    assert service().focus_seconds_remaining() == 6
    assert repository.get_focus_progress() == 4
    segment = snapshot("focus", 0, 6)
    assert repository.reset_active_timer(segment) == (5, 1)
    assert repository.get_summary_by_subject() == [("English", 10, 2)]
    monkeypatch.setattr(config, "DATABASE_PATH", normal_path)
    monkeypatch.setattr(config, "POMODORO_FOCUS_SECONDS", 1500)
    assert repository.get_focus_progress() == 893
    assert repository.get_pomodoro_state() == (0, 0)


def test_close_failure_on_choice_does_not_block_continue(monkeypatch):
    repository.save_active_timer(snapshot("choice", 0))
    timer = service()
    try:
        timer.restore_progress()
        wait_for(lambda: timer.current_phase == "choice")
        original = timer_service.save_active_timer
        monkeypatch.setattr(timer_service, "save_active_timer",
                            lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
        assert not timer.suspend_for_close()
        assert not timer.pause_event.is_set()
        monkeypatch.setattr(timer_service, "save_active_timer", original)
        assert timer.continue_focus()
        wait_for(lambda: timer.current_phase == "focus")
        assert timer.suspend_for_close()
        assert repository.load_active_timer().phase == "focus"
    finally:
        timer.reset_timer()


def test_gui_close_failure_keeps_window_open(tmp_path):
    saved = snapshot()
    repository.save_active_timer(saved)
    script = """
import sqlite3
import customtkinter as ctk
import gui
import timer_service
import session_repository as repository
saved = repository.load_active_timer()
gui.messagebox.showerror = lambda *a, **kw: None
def inspect(app):
    close = app.protocol('WM_DELETE_WINDOW')
    original = timer_service.save_active_timer
    def fail(_):
        raise sqlite3.OperationalError('disk full')
    timer_service.save_active_timer = fail
    try:
        app.tk.call(close)
        assert app.winfo_exists()
        assert repository.load_active_timer() == saved
    finally:
        timer_service.save_active_timer = original
        app.tk.call(close)
ctk.CTk.mainloop = inspect
gui.run_app()
"""
    process = child_process(script, tmp_path)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stdout + stderr


def child_process(script, tmp_path):
    environment = dict(os.environ, RECOVERY_TEST_DIR=str(tmp_path))
    prelude = """
import os
from pathlib import Path
import time
import config
config.DATA_DIRECTORY = Path(os.environ['RECOVERY_TEST_DIR'])
config.DATABASE_PATH = config.DATA_DIRECTORY / 'sessions.sqlite3'
"""
    return subprocess.Popen([sys.executable, "-u", "-c", prelude + script],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_gui_settings_save_cancel_failure_and_active_lock(tmp_path):
    script = """
import sqlite3
import customtkinter as ctk
import gui
import timer_service
import session_repository as repo

repo.reset_active_timer(repo.ActiveTimer('shared-seven', 'Pomodoro', 'Umum', 'focus', 1500, 1080))
services = []
original_service = gui.TimerService
def factory(*args, **kwargs):
    instance = original_service(*args, **kwargs)
    services.append(instance)
    return instance
gui.TimerService = factory
gui.messagebox.showerror = lambda *a, **kw: None
timer_service.winsound.PlaySound = lambda *a: None

def inspect(app):
    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)
    def button(text, parent=None):
        return next(w for w in descendants(parent or app)
                    if isinstance(w, ctk.CTkButton) and w.cget('text') == text)
    def displayed(value):
        return any(isinstance(w, ctk.CTkLabel) and str(w.cget('textvariable'))
                   and app.getvar(str(w.cget('textvariable'))) == value for w in descendants(app))
    def pump(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.update()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError('Timed out waiting for GUI')
    def open_settings(scope):
        button('Settings').invoke()
        app.update()
        dialog = next(w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel))
        radio = next(w for w in descendants(dialog)
                     if isinstance(w, ctk.CTkRadioButton) and w.cget('value') == scope)
        radio.invoke()
        return dialog
    try:
        app.update()
        service = services[0]
        subject = next(w for w in descendants(app)
                       if isinstance(w, gui.SubjectOptionMenu))
        assert displayed('00:18:00')
        dialog = open_settings('per_subject')
        button('Cancel', dialog).invoke()
        assert repo.get_focus_scope() == 'shared'
        assert displayed('00:18:00')
        dialog = open_settings('per_subject')
        button('Save', dialog).invoke()
        assert not dialog.winfo_exists()
        assert displayed('00:25:00')
        subject.set('Anki')
        repo.reset_active_timer(repo.ActiveTimer('anki-two', 'Pomodoro', 'Anki', 'focus', 1500, 1380))
        subject.set('Anki')
        assert displayed('00:23:00')
        dialog = open_settings('shared')
        button('Save', dialog).invoke()
        assert displayed('00:18:00')
        dialog = open_settings('per_subject')
        original_save = timer_service.set_focus_scope
        def fail(*args):
            raise sqlite3.OperationalError('disk full')
        timer_service.set_focus_scope = fail
        button('Save', dialog).invoke()
        assert dialog.winfo_exists()
        assert repo.get_focus_scope() == service.focus_scope == 'shared'
        assert displayed('00:18:00')
        assert any(isinstance(w, ctk.CTkLabel) and 'disk full' in w.cget('text')
                   for w in descendants(dialog))
        timer_service.set_focus_scope = original_save
        button('Save', dialog).invoke()
        assert displayed('00:23:00')
        assert any(isinstance(w, ctk.CTkLabel) and 'Separate target for each subject.' in w.cget('text')
                   for w in descendants(app))
        reopened = original_service(lambda _: None, lambda _: None, lambda *a: None)
        assert reopened.focus_scope == 'per_subject'
        assert reopened.focus_seconds_remaining('Anki') == 1380
        button('Start').invoke()
        pump(lambda: service.current_phase == 'focus' and button('Settings').cget('state') == 'disabled')
        button('Pause').invoke()
        pump(lambda: any(isinstance(w, ctk.CTkButton) and w.cget('text') == 'Resume'
                         for w in descendants(app)))
        assert button('Settings').cget('state') == 'disabled'
        button('Reset').invoke()
        assert button('Settings').cget('state') == 'normal'
        service.storage_blocked = True
        subject.set('Umum')
        assert button('Settings').cget('state') == 'disabled'
        service.storage_blocked = False
        original_read = timer_service.get_focus_progress
        timer_service.get_focus_progress = fail
        subject.set('Umum')
        assert button('Settings').cget('state') == 'disabled'
        timer_service.get_focus_progress = original_read
        button('Retry').invoke()
        assert button('Settings').cget('state') == 'normal'
    finally:
        app.tk.call(app.protocol('WM_DELETE_WINDOW'))
ctk.CTk.mainloop = inspect
gui.run_app()
"""
    process = child_process(script, tmp_path)
    stdout, stderr = process.communicate(timeout=20)
    assert process.returncode == 0, stdout + stderr


def test_running_process_crash_restores_last_durable_second(tmp_path):
    process = child_process("""
from timer_service import TimerService
timer = TimerService(lambda _: None, lambda _: None, lambda *a, **kw: None)
timer.start_timer(100, 'English')
while timer.remaining_seconds != 99:
    time.sleep(0.01)
(config.DATA_DIRECTORY / 'ready').touch()
time.sleep(30)
""", tmp_path)
    try:
        wait_for(lambda: (tmp_path / "ready").exists() or process.poll() is not None)
        assert process.poll() is None, process.communicate()
        process.kill()
        process.communicate(timeout=5)

        saved = repository.load_active_timer()
        assert saved.total_seconds == 100
        assert 0 < saved.remaining_seconds <= 99
        timer = service()
        try:
            assert timer.restore_progress() == saved
            threading.Event().wait(0.1)
            assert timer.pause_event.is_set()
            assert timer.remaining_seconds == saved.remaining_seconds
        finally:
            timer.reset_timer()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("phase", ["manual", "focus", "break"])
def test_crash_after_transaction_does_not_repeat_completion_or_debit(tmp_path, phase):
    saved = snapshot(phase, 1, 100, phase != "manual")
    repository.save_active_timer(saved)
    if phase == "break":
        repository.complete_pomodoro_focus("Umum", 1500)
    process = child_process("""
import session_repository as repo
from dataclasses import replace
timer = repo.load_active_timer()
if timer.phase == 'focus':
    repo.complete_pomodoro_focus(timer.subject, timer.total_seconds, timer)
elif timer.phase == 'manual':
    repo.save_session(timer.subject, timer.total_seconds, timer)
else:
    repo.consume_break_second(replace(timer, remaining_seconds=0))
os._exit(0)
""", tmp_path)
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stdout + stderr
    timer = service()
    try:
        restored = timer.restore_progress()
        if phase == "manual":
            assert restored is None
        else:
            assert restored.phase == "choice"
            wait_for(lambda: timer.current_phase == "choice")
        assert len(repository.get_recent_sessions()) == 1
        assert repository.get_pomodoro_state() == (
            (299, 1) if phase == "break" else (300, 1) if phase == "focus" else (0, 0))
    finally:
        timer.reset_timer()


def test_preview_recovery_does_not_touch_normal_database(tmp_path):
    saved = snapshot()
    repository.save_active_timer(saved)
    environment = dict(os.environ, LOCALAPPDATA=str(tmp_path), STUDY_TIMER_PREVIEW="1")
    script = """
import config
import session_repository as repo
from timer_service import TimerService
timer = repo.ActiveTimer('preview-session', 'Pomodoro', 'Umum', 'focus', 10, 7, True)
repo.save_active_timer(timer)
service = TimerService(lambda _: None, lambda _: None, lambda *a, **kw: None)
assert service.restore_progress() == timer
assert service.pause_event.is_set()
assert service.remaining_seconds == 7
assert service.suspend_for_close()
assert repo.load_active_timer() == timer
"""
    result = subprocess.run([sys.executable, "-c", script], env=environment,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert repository.load_active_timer() == saved
    assert (tmp_path / "StudyTimerPreview" / "study_sessions.sqlite3").exists()


def test_instance_lock_rejects_second_process_and_releases_after_crash(tmp_path):
    process = child_process("""
from instance_lock import InstanceLock
with InstanceLock(config.DATABASE_PATH):
    (config.DATA_DIRECTORY / 'locked').touch()
    time.sleep(30)
""", tmp_path)
    try:
        wait_for(lambda: (tmp_path / "locked").exists() or process.poll() is not None)
        assert process.poll() is None, process.communicate()
        with pytest.raises(AlreadyRunningError):
            with InstanceLock(config.DATABASE_PATH):
                pass
        with InstanceLock(tmp_path / "preview.sqlite3"):
            pass
        process.kill()
        process.communicate(timeout=5)
        with InstanceLock(config.DATABASE_PATH):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
