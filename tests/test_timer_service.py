import queue
import threading
import wave
import time
import sqlite3
from array import array

import pytest

import config
import timer_service
import session_repository as repository
from timer_service import TimerService


@pytest.fixture(autouse=True)
def silent_alarm(monkeypatch, tmp_path):
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *_: None)
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")


def make_service():
    return TimerService(lambda _: None, lambda _: None, lambda *_, **__: None)


@pytest.mark.parametrize("volume", [0, 25, 50, 100, 200, 400])
def test_tick_volume_scales_audio_and_persists_without_changing_timing(volume, monkeypatch):
    service = make_service()
    reopened = None
    try:
        service.change_focus_scope("shared", "Umum", True, volume)
        with wave.open(str(service._tick_source_path), "rb") as source:
            params = source.getparams()
            original = array("h", source.readframes(source.getnframes()))
        with wave.open(str(service.tick_sound_path), "rb") as scaled:
            assert scaled.getparams() == params
            actual = array("h", scaled.readframes(scaled.getnframes()))
        assert actual == array("h", (round(sample * volume / 100) for sample in original))
        playback = []
        monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *args: playback.append(args))
        service._play_tick()
        if volume == 0:
            assert not playback
        else:
            assert playback[0][0] == str(service.tick_sound_path)
            assert not playback[0][1] & timer_service.winsound.SND_LOOP
        reopened = make_service()
        assert reopened.tick_volume == volume
        assert reopened.tick_sound_enabled
    finally:
        service.suspend_for_close()
        if reopened is not None:
            reopened.suspend_for_close()


def test_failed_volume_save_keeps_all_settings_unchanged():
    service = make_service()
    original_path = service.tick_sound_path
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TRIGGER fail_volume BEFORE UPDATE OF tick_volume ON pomodoro_settings
            BEGIN SELECT RAISE(ABORT, 'disk full'); END""")
    try:
        with pytest.raises(sqlite3.DatabaseError):
            service.change_focus_scope("per_subject", "Umum", True, 25)
        assert service.focus_scope == repository.get_focus_scope() == "shared"
        assert service.tick_volume == repository.get_tick_volume() == 100
        assert not service.tick_sound_enabled and not repository.get_tick_sound()
        assert service.tick_sound_path == original_path
    finally:
        service.suspend_for_close()


def test_tick_volume_migration_preserves_previous_settings():
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("CREATE TABLE pomodoro_settings (id INTEGER PRIMARY KEY, focus_scope TEXT, tick_sound INTEGER)")
        connection.execute("INSERT INTO pomodoro_settings VALUES (1, 'per_subject', 1)")
    assert repository.get_tick_volume() == 100
    assert repository.get_tick_sound()
    assert repository.get_focus_scope() == "per_subject"


def test_tick_boost_migration_preserves_saved_volume():
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        connection.execute("""CREATE TABLE pomodoro_settings (
            id INTEGER PRIMARY KEY, focus_scope TEXT, tick_sound INTEGER,
            tick_volume INTEGER NOT NULL DEFAULT 100 CHECK (tick_volume BETWEEN 0 AND 100))""")
        connection.execute("INSERT INTO pomodoro_settings VALUES (1, 'per_subject', 1, 42)")
    assert repository.get_tick_volume() == 42
    repository.set_focus_scope("per_subject", "Umum", tick_volume=400)
    assert repository.get_tick_volume() == 400
    assert repository.get_tick_sound()
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        assert connection.execute("SELECT tick_volume, tick_volume_percent FROM pomodoro_settings").fetchone() == (100, 400)


@pytest.mark.parametrize("volume", [-1, 401])
def test_invalid_tick_boost_keeps_saved_volume(volume):
    service = make_service()
    with pytest.raises(ValueError):
        service.change_focus_scope("shared", "Umum", True, volume)
    assert service.tick_volume == repository.get_tick_volume() == 100


def test_tick_starts_immediately_and_stops_on_pause_reset(monkeypatch):
    service = make_service()
    service.change_tick_sound(True)
    playback = queue.Queue()
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *args: playback.put(args))
    service.start_timer(30, "Umum")
    try:
        sound, flags = playback.get(timeout=0.8)
        assert sound == str(service.tick_sound_path)
        assert not flags & timer_service.winsound.SND_LOOP
        assert service.remaining_seconds == 30
        service.pause_timer()
        assert playback.get(timeout=0.8) == (None, 0)
        service.resume_timer()
        assert playback.get(timeout=0.8)[0] == str(service.tick_sound_path)
        service.reset_timer()
        assert playback.get(timeout=0.8) == (None, 0)
        assert not service._tick_playing
    finally:
        service.reset_timer()


def test_tick_preference_survives_new_service_and_audio_has_silent_tail():
    service = make_service()
    assert not service.tick_sound_enabled
    service.change_tick_sound(True)
    assert make_service().tick_sound_enabled
    service.change_tick_sound(False)
    assert not make_service().tick_sound_enabled
    with wave.open(str(service.tick_sound_path), "rb") as sound:
        assert sound.getnchannels() == 1
        assert sound.getsampwidth() == 2
        assert sound.getnframes() == sound.getframerate()
        first_millisecond = sound.readframes(round(sound.getframerate() * 0.001))
        assert any(first_millisecond)
        sound.setpos(round(sound.getframerate() * 0.035))
        assert not any(sound.readframes(sound.getnframes()))


def test_tick_matches_displayed_seconds_even_when_storage_is_slow(monkeypatch):
    service = make_service()
    service.change_tick_sound(True)
    playback = queue.Queue()
    displayed = []
    saving = threading.Event()
    release_save = threading.Event()
    original_checkpoint = service._checkpoint

    def slow_checkpoint(timer):
        if timer.remaining_seconds == 29:
            saving.set()
            assert release_save.wait(3)
        original_checkpoint(timer)

    service.set_countdown = displayed.append
    monkeypatch.setattr(service, "_checkpoint", slow_checkpoint)
    monkeypatch.setattr(timer_service.winsound, "PlaySound",
                        lambda sound, flags: playback.put((sound, flags, displayed[-1])))
    service.start_timer(30, "Umum")
    try:
        assert playback.get(timeout=0.8)[2] == "00:00:30"
        assert saving.wait(2)
        # A slow checkpoint must not emit ticks while the old second is displayed.
        with pytest.raises(queue.Empty):
            playback.get(timeout=0.3)
        release_save.set()
        sound, flags, value = playback.get(timeout=1)
        assert sound == str(service.tick_sound_path)
        assert not flags & timer_service.winsound.SND_LOOP
        assert value == "00:00:29"
    finally:
        release_save.set()
        service.reset_timer()


def test_alarm_keeps_ringing_until_stopped(monkeypatch):
    service = make_service()
    playback = queue.Queue()
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *args: playback.put(args))
    worker = threading.Thread(target=service._beep, daemon=True)
    worker.start()
    try:
        sound, flags = playback.get(timeout=2)
        assert sound == str(timer_service.ALARM_SOUND_PATH)
        assert flags & timer_service.winsound.SND_LOOP
        assert flags & timer_service.winsound.SND_ASYNC
        assert flags & timer_service.winsound.SND_FILENAME
        assert worker.is_alive()
        assert service.is_alarm_active
        service.stop_alarm()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not service.is_alarm_active
        assert playback.get(timeout=2) == (None, 0)
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
        if not save_succeeds:
            deadline = time.monotonic() + 2
            while not service.pause_event.is_set() and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            assert service.pause_event.is_set()
            assert not service.is_alarm_active
            assert saved == [("Anki", 25)]
            return
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
    service.update_control_state = lambda *args, **kwargs: (
        alarms.put(service.current_phase) if service.is_alarm_active else None
    )

    def countdown(*args, **kwargs):
        phases.append(service.current_phase)
        return True

    monkeypatch.setattr(service, "_run_countdown", countdown)
    service.start_pomodoro("Anki")
    try:
        for index in range(5):
            assert alarms.get(timeout=2) == "focus"
            assert phases == ["focus"] * (index + 1)
            assert service.break_balance_seconds == [300, 600, 900, 1800, 2100][index]
            service.stop_alarm()
            deadline = time.monotonic() + 2
            while service.current_phase != "choice" and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            assert service.current_phase == "choice"
            assert phases == ["focus"] * (index + 1)
            if index < 4:
                assert service.continue_focus()
        service.reset_timer()
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
    sounds = []
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *args: sounds.append(args))
    service.reset_timer()
    sounds.clear()
    service._beep()
    assert not sounds
    assert not service.is_alarm_active


def test_stop_alarm_stops_audio_before_returning(monkeypatch):
    service = make_service()
    calls = []
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *args: calls.append(args))
    service.is_alarm_active = True
    service.stop_alarm()
    # No worker needs to wake or finish a beep for Windows to receive the stop.
    assert calls == [(None, 0)]
    assert service.alarm_stop_event.is_set()


def test_stop_before_playback_starts_does_not_restart_sound(monkeypatch):
    service = make_service()
    calls = []
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *args: calls.append(args))
    service.update_control_state = lambda *args: service.stop_alarm()
    service._beep()
    assert calls
    assert all(sound is None for sound, _flags in calls)
    assert not service.is_alarm_active


def test_bundled_alarm_is_a_valid_short_wav():
    with wave.open(str(timer_service.ALARM_SOUND_PATH), "rb") as sound:
        assert sound.getnchannels() == 1
        assert sound.getsampwidth() == 2
        assert 0.34 < sound.getnframes() / sound.getframerate() < 0.36
