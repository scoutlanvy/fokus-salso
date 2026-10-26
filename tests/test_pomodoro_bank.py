import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import config
import session_repository as repository
import timer_service
from timer_service import TimerService


@pytest.fixture(autouse=True)
def isolated_bank(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *_: None)


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.005)
    raise AssertionError("Timed out waiting for timer state")


@pytest.fixture
def service():
    instance = TimerService(lambda _: None, lambda _: None, lambda *_, **__: None)
    yield instance
    instance.reset_timer()
    if instance.timer_thread:
        instance.timer_thread.join(3)
        assert not instance.timer_thread.is_alive()


@pytest.fixture
def fast_clock(monkeypatch):
    # Accelerate only the service clock; synchronization deadlines stay real.
    monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 20))


def test_migrates_existing_history_and_persists_rewards():
    repository.save_session("English", 60)
    assert repository.get_pomodoro_state() == (0, 0)
    for index, expected in enumerate((300, 600, 900, 1800, 2100)):
        assert repository.complete_pomodoro_focus("Umum", 1500) == (expected, (index + 1) % 4)
    assert repository.get_pomodoro_state() == (2100, 1)
    assert ("English", 60, 1) in repository.get_summary_by_subject()
    assert ("Umum", 7500, 5) in repository.get_summary_by_subject()
    assert len(repository.get_recent_sessions()) == 6


def test_focus_credit_rolls_back_session_when_state_write_fails():
    repository.get_pomodoro_state()
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TRIGGER fail_credit BEFORE UPDATE ON pomodoro_state
                            BEGIN SELECT RAISE(ABORT, 'disk failure'); END""")
    with pytest.raises(sqlite3.DatabaseError):
        repository.complete_pomodoro_focus("Umum", 1500)
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions() == []


def test_concurrent_awards_are_not_lost_or_duplicated():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: repository.complete_pomodoro_focus("Umum", 1500), range(8)))
    assert sorted(balance for balance, _ in results) == [300, 600, 900, 1800, 2100, 2400, 2700, 3600]
    assert repository.get_pomodoro_state() == (3600, 0)
    assert len(repository.get_recent_sessions()) == 8


def test_cannot_overdraw_balance():
    assert repository.get_pomodoro_state() == (0, 0)
    with pytest.raises(ValueError):
        repository.consume_break_second()
    assert repository.get_pomodoro_state() == (0, 0)


def test_idle_partial_break_returns_idle_and_preserves_rest(service, fast_clock):
    repository.complete_pomodoro_focus("Umum", 1500)
    assert service.start_break(2)
    assert not service.start_break(2)
    assert not service.continue_focus()
    wait_for(lambda: service.is_alarm_active)
    assert repository.get_pomodoro_state() == (298, 1)
    assert not service.start_break(1)
    service.stop_alarm()
    service.timer_thread.join(2)
    assert not service.is_running
    assert service.break_balance_seconds == 298


def test_can_spend_exactly_all_balance(service, fast_clock):
    repository.complete_pomodoro_focus("Umum", 1500)
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("UPDATE pomodoro_state SET balance_seconds = 2 WHERE id = 1")
    assert service.start_break(2)
    wait_for(lambda: service.is_alarm_active)
    assert repository.get_pomodoro_state() == (0, 1)
    service.stop_alarm()
    service.timer_thread.join(2)
    assert not service.is_running
    assert not service.start_break(1)


def test_manual_completion_does_not_award_break(service, monkeypatch):
    monkeypatch.setattr(service, "_run_countdown", lambda *args, **kwargs: True)
    service.start_timer(10, "Umum")
    wait_for(lambda: service.is_alarm_active)
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions()[0][:2] == ("Umum", 10)


def test_pause_skip_reset_and_reopen_preserve_unused_balance(service, fast_clock):
    repository.complete_pomodoro_focus("Umum", 1500)
    assert service.start_break(30)
    wait_for(lambda: service.break_balance_seconds < 300)
    service.pause_timer()
    # Allow any debit already in flight at the instant of Pause to settle.
    threading.Event().wait(0.08)
    balance = repository.get_pomodoro_state()
    service.skip_break()
    threading.Event().wait(0.15)
    assert repository.get_pomodoro_state() == balance
    assert not service.skip_break_event.is_set()
    service.resume_timer()
    wait_for(lambda: service.break_balance_seconds < balance[0])
    service.skip_break()
    wait_for(lambda: service.current_phase == "choice")
    remaining = repository.get_pomodoro_state()
    threading.Event().wait(0.1)
    assert repository.get_pomodoro_state() == remaining
    service.reset_timer()
    service.timer_thread.join(2)
    reopened = TimerService(lambda _: None, lambda _: None, lambda *_, **__: None)
    assert (reopened.break_balance_seconds, reopened.cycle_position) == remaining
    assert not reopened.is_running


@pytest.mark.parametrize("duration", [0, -1, 301, 1.5, True, "5"])
def test_invalid_break_does_not_spend_balance(service, duration):
    repository.complete_pomodoro_focus("Umum", 1500)
    assert not service.start_break(duration)
    assert repository.get_pomodoro_state() == (300, 1)


def test_focus_requires_choice_and_guards_double_clicks(service, monkeypatch, fast_clock):
    original = service._run_countdown
    monkeypatch.setattr(service, "_run_countdown", lambda *args, **kwargs:
                        True if service.current_phase == "focus" else original(*args, **kwargs))
    service.start_pomodoro("Umum")
    service.start_pomodoro("English")
    wait_for(lambda: service.is_alarm_active)
    assert not service.continue_focus()
    assert len(repository.get_recent_sessions()) == 1
    service.stop_alarm()
    wait_for(lambda: service.current_phase == "choice")
    service.pause_timer()
    assert not service.pause_event.is_set()
    assert service.start_break(1)
    assert not service.start_break(1)
    assert not service.continue_focus()
    wait_for(lambda: service.is_alarm_active)
    assert service.break_balance_seconds == 299
    service.stop_alarm()
    wait_for(lambda: service.current_phase == "choice")
    assert service.continue_focus()
    assert not service.continue_focus()
    wait_for(lambda: service.is_alarm_active)
    assert repository.get_pomodoro_state() == (599, 2)
    assert len(repository.get_recent_sessions()) == 2


def test_reset_interrupts_focus_without_credit(service):
    service.start_pomodoro("Umum")
    wait_for(lambda: service.current_phase == "focus")
    service.reset_timer()
    service.timer_thread.join(2)
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions() == []


def test_focus_storage_failure_can_retry_without_duplicate_credit(service, monkeypatch):
    monkeypatch.setattr(service, "_run_countdown", lambda *args, **kwargs: True)
    original = timer_service.complete_pomodoro_focus
    calls = []

    def fail_once(*args):
        calls.append(args)
        if len(calls) == 1:
            raise sqlite3.OperationalError("disk full")
        return original(*args)

    monkeypatch.setattr(timer_service, "complete_pomodoro_focus", fail_once)
    service.start_pomodoro("Umum")
    wait_for(lambda: service.pause_event.is_set())
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions() == []
    assert not service.is_alarm_active
    service.resume_timer()
    wait_for(lambda: service.is_alarm_active)
    assert repository.get_pomodoro_state() == (300, 1)
    assert len(repository.get_recent_sessions()) == 1
    assert len(calls) == 2


def test_failed_debit_pauses_and_retries_pending_second(service, monkeypatch, fast_clock):
    repository.complete_pomodoro_focus("Umum", 1500)
    original = timer_service.consume_break_second
    calls = []

    def fail_once(*args):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("disk full")
        return original(*args)

    monkeypatch.setattr(timer_service, "consume_break_second", fail_once)
    assert service.start_break(1)
    wait_for(lambda: service.pause_event.is_set())
    assert service.remaining_seconds == 1
    assert repository.get_pomodoro_state() == (300, 1)
    threading.Event().wait(0.1)
    assert len(calls) == 1
    service.resume_timer()
    wait_for(lambda: service.is_alarm_active)
    assert repository.get_pomodoro_state() == (299, 1)
    assert len(calls) == 2


def test_reset_during_failed_save_cancels_retry(service, monkeypatch):
    monkeypatch.setattr(service, "_run_countdown", lambda *args, **kwargs: True)
    def fail(*args):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(timer_service, "complete_pomodoro_focus", fail)
    service.start_pomodoro("Umum")
    wait_for(lambda: service.pause_event.is_set())
    service.reset_timer()
    service.timer_thread.join(2)
    assert not service.timer_thread.is_alive()
    assert repository.get_pomodoro_state() == (0, 0)
    assert repository.get_recent_sessions() == []
