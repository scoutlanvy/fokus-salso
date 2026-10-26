import queue
import threading

import pytest

import config
import timer_service
from timer_service import TimerService


@pytest.fixture(autouse=True)
def silent_alarm(monkeypatch):
    monkeypatch.setattr(timer_service.winsound, "Beep", lambda *_: None)


def make_service():
    return TimerService(lambda _: None, lambda _: None, lambda *_, **__: None)


def test_alarm_keeps_ringing_until_stopped(monkeypatch):
    service = make_service()
    beeps = queue.Queue()
    monkeypatch.setattr(timer_service.winsound, "Beep", lambda *_: beeps.put(True))
    worker = threading.Thread(target=service._beep, daemon=True)
    worker.start()
    try:
        for _ in range(5):
            beeps.get(timeout=2)
        assert worker.is_alive()
        assert service.is_alarm_active
        service.stop_alarm()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not service.is_alarm_active
    finally:
        service.stop_alarm()
        worker.join(timeout=2)


@pytest.mark.parametrize("save_succeeds", [True, False])
def test_manual_session_saved_before_alarm_and_finishes_after_acknowledgement(
    monkeypatch, save_succeeds
):
    service = make_service()
    alarm_ready = threading.Event()
    saved = []
    statuses = []
    service.set_status = statuses.append
    service.update_control_state = lambda *args, **kwargs: (
        alarm_ready.set() if service.is_alarm_active else None
    )
    monkeypatch.setattr(service, "_run_countdown", lambda *args: True)

    def save(subject, seconds):
        saved.append((subject, seconds))
        return save_succeeds

    monkeypatch.setattr(service, "_save_session", save)
    service.start_timer(25, "Anki")
    try:
        assert alarm_ready.wait(2)
        assert saved == [("Anki", 25)]
        assert statuses[-1] == (
            "Completed & saved" if save_succeeds else "Completed (save failed)"
        )
        assert service.is_running
        service.stop_alarm()
        service.timer_thread.join(timeout=2)
        assert not service.timer_thread.is_alive()
        assert not service.is_running
        assert not service.is_alarm_active
    finally:
        service.reset_timer()
        service.timer_thread.join(timeout=2)


def test_pomodoro_waits_for_each_alarm_before_next_phase(monkeypatch):
    service = make_service()
    alarms = queue.Queue()
    phases = []
    saved = []
    monkeypatch.setattr(config, "POMODORO_TOTAL_SESSIONS", 2)
    service.update_control_state = lambda *args, **kwargs: (
        alarms.put(service.current_phase) if service.is_alarm_active else None
    )

    def countdown(*args, **kwargs):
        phases.append(service.current_phase)
        return True

    monkeypatch.setattr(service, "_run_countdown", countdown)
    monkeypatch.setattr(service, "_save_session", lambda *args: saved.append(args) or True)
    service.start_pomodoro("Anki")
    try:
        expected = ["focus", "short_break", "focus", "long_break"]
        for index, phase in enumerate(expected):
            assert alarms.get(timeout=2) == phase
            assert phases == expected[:index + 1]
            assert len(saved) == (index // 2) + 1
            service.stop_alarm()
        service.timer_thread.join(timeout=2)
        assert not service.timer_thread.is_alive()
        assert not service.is_running
    finally:
        service.reset_timer()
        service.timer_thread.join(timeout=2)


def test_reset_during_alarm_cancels_remaining_pomodoro_phases(monkeypatch):
    service = make_service()
    alarm_ready = threading.Event()
    phases = []
    service.update_control_state = lambda *args, **kwargs: (
        alarm_ready.set() if service.is_alarm_active else None
    )
    monkeypatch.setattr(service, "_run_countdown", lambda *args, **kwargs: phases.append(service.current_phase) or True)
    monkeypatch.setattr(service, "_save_session", lambda *args: True)
    service.start_pomodoro("Anki")
    try:
        assert alarm_ready.wait(2)
        service.reset_timer()
        service.timer_thread.join(timeout=2)
        assert not service.timer_thread.is_alive()
        assert phases == ["focus"]
        assert not service.is_alarm_active
        assert not service.is_running
    finally:
        service.reset_timer()
        service.timer_thread.join(timeout=2)


def test_alarm_cannot_be_paused_or_skipped():
    service = make_service()
    service.is_running = True
    service.is_alarm_active = True
    service.current_phase = "short_break"
    service.pause_timer()
    service.skip_break()
    assert not service.pause_event.is_set()
    assert not service.skip_break_event.is_set()


def test_cancelled_timer_does_not_start_alarm(monkeypatch):
    service = make_service()
    beeps = []
    monkeypatch.setattr(timer_service.winsound, "Beep", lambda *args: beeps.append(args))
    service.reset_timer()
    service._beep()
    assert not beeps
    assert not service.is_alarm_active
