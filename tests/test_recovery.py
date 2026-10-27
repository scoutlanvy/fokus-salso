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
        reset.invoke()
        app.update()
        assert repository.load_active_timer() is None
        assert mode.cget('state') == 'normal'
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
    assert len(repository.get_recent_sessions()) == 1


def test_legacy_database_gains_progress_tables_without_changing_history():
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TABLE study_sessions (id INTEGER PRIMARY KEY,
            subject TEXT NOT NULL, duration_seconds INTEGER NOT NULL, recorded_at TEXT NOT NULL)""")
        connection.execute("INSERT INTO study_sessions VALUES (1, 'Anki', 60, '2026-01-01T12:00:00+07:00')")
    assert repository.load_active_timer() is None
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions() == [("Anki", 60, "2026-01-01T12:00:00+07:00")]


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
