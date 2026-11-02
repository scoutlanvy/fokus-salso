import sqlite3
import threading
import time
import winsound
from dataclasses import replace
from uuid import uuid4
from pathlib import Path
from typing import Callable, Optional

import config
from session_repository import (
    save_session, get_pomodoro_state, complete_pomodoro_focus, consume_break_second,
    ActiveTimer, load_active_timer, save_active_timer, clear_active_timer, reset_active_timer,
    get_focus_progress, get_focus_scope, set_focus_scope, get_tick_sound, set_tick_sound,
)

Callback = Callable[[str], None]
ControlStateCallback = Callable[[bool, bool, bool], None]
ALARM_SOUND_PATH = Path(__file__).with_name("alarm.wav")


class TimerService:
    def __init__(
        self,
        set_countdown: Callback,
        set_status: Callback,
        update_control_state: ControlStateCallback,
        on_storage_error: Optional[Callback] = None,
    ):
        self.set_countdown = set_countdown
        self.set_status = set_status
        self.update_control_state = update_control_state
        self.on_storage_error = on_storage_error
        self.timer_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.skip_break_event = threading.Event()
        self.alarm_stop_event = threading.Event()
        self._alarm_lock = threading.Lock()
        self.is_alarm_active = False
        self.remaining_seconds = 0
        self.is_running = False
        self.current_phase = "manual"
        self.break_balance_seconds = 0
        self.cycle_position = 0
        self._command_lock = threading.RLock()
        self._choice_event = threading.Event()
        self._choice = None
        self._progress = None
        self._restoring = False
        self._focus_break_event = threading.Event()
        self._storage_retry = False
        self.focus_scope = "shared"
        self.tick_sound_enabled = False
        self.tick_sound_path = Path(__file__).with_name("tick.wav")
        self._tick_playing = False
        self.focus_read_failed = False
        self.storage_blocked = not self._load_balance()

    def _checkpoint(self, timer):
        save_active_timer(timer)
        self._progress = timer

    def _prepare_phase(self, phase, subject, seconds, return_to_choice=False):
        if self._restoring:
            self._restoring = False
            return True
        def prepare():
            duration = (config.POMODORO_FOCUS_SECONDS - get_focus_progress(subject)
                        if phase == "focus" else seconds)
            timer = ActiveTimer(str(uuid4()), "Manual" if phase == "manual" else "Pomodoro",
                                subject, phase, duration, duration, return_to_choice)
            self._checkpoint(timer)
        return self._persist_with_retry(prepare)

    def focus_seconds_remaining(self, subject="Umum"):
        """Read the next idle target; callers must not start if reading fails."""
        try:
            remaining = config.POMODORO_FOCUS_SECONDS - get_focus_progress(subject)
            self.focus_read_failed = False
            return remaining
        except (OSError, sqlite3.Error) as error:
            self.focus_read_failed = True
            self._storage_error(error)
            return None

    def can_change_settings(self):
        return not (self.is_running or self.is_alarm_active or self.storage_blocked
                    or self.focus_read_failed or self._storage_retry
                    or (self.timer_thread is not None and self.timer_thread.is_alive()))

    def change_focus_scope(self, scope, subject):
        """Keep the current UI preference unless the complete save succeeds."""
        with self._command_lock:
            if not self.can_change_settings():
                raise ValueError("Settings can only change while the timer is idle and storage is available.")
            progress = set_focus_scope(scope, subject)
            self.focus_scope = scope
            return config.POMODORO_FOCUS_SECONDS - progress

    def change_tick_sound(self, enabled):
        with self._command_lock:
            if not self.can_change_settings():
                raise ValueError("Settings can only change while the timer is idle and storage is available.")
            self.tick_sound_enabled = set_tick_sound(enabled)
            return self.tick_sound_enabled

    def focus_target_progress(self):
        """Active progress includes the carried portion and this running segment."""
        with self._command_lock:
            focus = self._progress
            if focus is not None and focus.phase == "break":
                focus = focus.suspended_focus
            if focus is not None and focus.mode == "Pomodoro" and focus.phase == "focus":
                return max(0, config.POMODORO_FOCUS_SECONDS - focus.remaining_seconds)
            return None

    def restore_progress(self):
        """Called after GUI initialization; recovered countdowns always start paused."""
        try:
            timer = load_active_timer()
            if (timer is not None and timer.phase == "break"
                    and timer.remaining_seconds == 0 and timer.suspended_focus is not None):
                timer = timer.suspended_focus
                save_active_timer(timer)
            if timer is not None and (timer.phase == "done" or (
                    timer.phase == "break" and timer.remaining_seconds == 0
                    and not timer.return_to_choice)):
                clear_active_timer()
                timer = None
        except (OSError, sqlite3.Error) as error:
            self.storage_blocked = True
            self._storage_error(error)
            self.update_control_state(False)
            return None
        if self.storage_blocked or timer is None:
            return None
        if timer.phase == "break" and timer.remaining_seconds == 0:
            timer = replace(timer, phase="choice")
        self._progress = timer
        self.remaining_seconds = timer.remaining_seconds
        self.current_phase = "starting" if timer.phase == "choice" else timer.phase
        self.is_running = True
        self.stop_event.clear()
        if timer.phase == "choice":
            target, args = self._restored_choice_loop, (timer.subject,)
        else:
            self.pause_event.set()
            self._restoring = True
            if timer.phase == "manual":
                target, args = self.countdown_loop, (timer.total_seconds, timer.subject)
            else:
                target, args = self.pomodoro_loop, (
                    timer.subject, timer.phase, timer.total_seconds, timer.return_to_choice)
        self.timer_thread = threading.Thread(target=target, args=args, daemon=True)
        self.timer_thread.start()
        return timer

    def _restored_choice_loop(self, subject):
        choice = self._wait_for_choice()
        if choice is not None:
            self.pomodoro_loop(subject, *choice, return_to_choice=True)
        else:
            self.is_running = False

    def suspend_for_close(self):
        """Freeze and save before stopping. A failed save leaves the window usable."""
        with self._command_lock:
            if (self.is_running and not self.is_alarm_active
                    and self.current_phase in ("manual", "focus", "break", "starting")):
                self.pause_event.set()
                self._stop_tick()
            try:
                if self._progress is not None:
                    save_active_timer(self._progress)
            except (OSError, sqlite3.Error) as error:
                if self.current_phase == "starting" and self._progress is not None:
                    self.current_phase = self._progress.phase
                self._storage_error(error)
                self.set_status("Could not save progress - Resume to retry or close again")
                self.update_control_state(True, True)
                return False
            self.stop_event.set()
            self._choice_event.set()
            self.stop_alarm()
        if self.timer_thread is not None:
            self.timer_thread.join()
        return True

    def _load_balance(self) -> bool:
        try:
            balance, position = get_pomodoro_state()
            scope = get_focus_scope()
            self.tick_sound_enabled = get_tick_sound()
            self.break_balance_seconds, self.cycle_position = balance, position
            self.focus_scope = scope
            return True
        except (OSError, sqlite3.Error) as error:
            self._storage_error(error)
            return False

    def _storage_error(self, error: Exception) -> None:
        message = f"Storage error: {error}"
        self.set_status(message)
        if self.on_storage_error is not None:
            self.on_storage_error(message)

    def _persist_with_retry(self, operation) -> bool:
        """Pause on failure. Resume retries the same transaction before proceeding."""
        while not self.stop_event.is_set():
            while self.pause_event.is_set() and not self.stop_event.wait(0.05):
                pass
            with self._command_lock:
                if self.stop_event.is_set():
                    return False
                if self.pause_event.is_set():
                    continue
                try:
                    self._storage_retry = True
                    result = operation()
                    self._storage_retry = False
                    if result is not None:
                        self.break_balance_seconds, self.cycle_position = result
                    return True
                except (OSError, sqlite3.Error) as error:
                    self.pause_event.set()
                    self._stop_tick()
                    self._storage_error(error)
                    self.set_status("Storage error - Resume to retry, or Reset")
                    self.update_control_state(True, True, False)
            while self.pause_event.is_set() and not self.stop_event.wait(0.05):
                pass
        return False

    def _save_session(self, subject: str, total_seconds: int) -> bool:
        save_session(subject, total_seconds, self._progress)
        if self._progress is not None:
            self._progress = replace(self._progress, phase="done", remaining_seconds=0)
        return True

    def format_hms(self, total_seconds: int) -> str:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _beep(self) -> None:
        with self._alarm_lock:
            if self.stop_event.is_set():
                return
            self.alarm_stop_event.clear()
            self.is_alarm_active = True
        self.set_countdown("00:00:00")
        self.update_control_state(True, False, False)
        try:
            with self._alarm_lock:
                if not self.stop_event.is_set() and not self.alarm_stop_event.is_set():
                    winsound.PlaySound(
                        str(ALARM_SOUND_PATH),
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
                    )
            while not self.stop_event.is_set() and not self.alarm_stop_event.wait(0.05):
                pass
        finally:
            with self._alarm_lock:
                winsound.PlaySound(None, 0)
                self.is_alarm_active = False

    def stop_alarm(self) -> None:
        with self._alarm_lock:
            self.alarm_stop_event.set()
            winsound.PlaySound(None, 0)
            self._tick_playing = False

    def _play_tick(self):
        with self._alarm_lock:
            if (self.tick_sound_enabled
                    and not self.pause_event.is_set() and not self.stop_event.is_set()
                    and not self.is_alarm_active):
                winsound.PlaySound(str(self.tick_sound_path),
                                   winsound.SND_FILENAME | winsound.SND_ASYNC)
                self._tick_playing = True

    def _stop_tick(self):
        with self._alarm_lock:
            if self._tick_playing:
                winsound.PlaySound(None, 0)
                self._tick_playing = False

    def _run_countdown(
        self,
        total_seconds: int,
        status: str,
        can_skip_break: bool = False,
    ) -> bool:
        try:
            return self._countdown_intervals(total_seconds, status, can_skip_break)
        finally:
            self._stop_tick()

    def _countdown_intervals(
        self,
        total_seconds: int,
        status: str,
        can_skip_break: bool = False,
    ) -> bool:
        self.remaining_seconds = (self._progress.remaining_seconds
                                  if self._progress is not None else total_seconds)
        self.skip_break_event.clear()
        self.update_control_state(True, self.pause_event.is_set(), can_skip_break)
        self.set_status("Paused - Resume to continue" if self.pause_event.is_set() else status)

        self.set_countdown(self.format_hms(self.remaining_seconds))
        elapsed = 0.0
        previous = time.monotonic()
        while self.pause_event.is_set() and not self.stop_event.wait(0.05):
            if self._focus_break_event.is_set():
                return False
            previous = time.monotonic()
        while self.remaining_seconds > 0 and not self.stop_event.is_set():
            if self._focus_break_event.is_set():
                return False
            if can_skip_break and self.skip_break_event.is_set():
                self.set_countdown("00:00:00")
                return False

            if self.pause_event.is_set():
                self._stop_tick()
                self.stop_event.wait(0.05)
                previous = time.monotonic()
                continue
            if not self._tick_playing:
                self._play_tick()
            self.stop_event.wait(0.05)
            now = time.monotonic()
            if self._focus_break_event.is_set():
                return False
            if self.stop_event.is_set() or self.pause_event.is_set() or self.skip_break_event.is_set():
                previous = now
                if self.pause_event.is_set():
                    self._stop_tick()
                continue
            elapsed += now - previous
            previous = now
            if elapsed < 1:
                continue
            # Do not catch up after a suspended machine or slow disk: only a
            # single displayed second can be awaiting its durable debit.
            elapsed = 0.0
            with self._command_lock:
                if self.stop_event.is_set():
                    return False
                if self.pause_event.is_set():
                    continue
            def tick():
                if self._focus_break_event.is_set():
                    return None
                timer = replace(self._progress, remaining_seconds=self.remaining_seconds - 1)
                if self.current_phase == "break":
                    result = consume_break_second(timer)
                    self._progress = timer
                else:
                    self._checkpoint(timer)
                    result = None
                self.remaining_seconds = timer.remaining_seconds
                return result
            try:
                if not self._persist_with_retry(tick):
                    return False
            except ValueError:
                self._load_balance()
                self.set_status("Break balance used by another window")
                return False
            previous = time.monotonic()
            with self._command_lock:
                self.set_countdown(self.format_hms(self.remaining_seconds))
                if self.remaining_seconds > 0:
                    self._play_tick()
                if self.current_phase == "break":
                    self.update_control_state(True, False, can_skip_break)

        return not self.stop_event.is_set() and self.remaining_seconds == 0

    def countdown_loop(self, total_seconds: int, subject: str) -> None:
        self.current_phase = "manual"
        if not self._prepare_phase("manual", subject, total_seconds):
            self.is_running = False
            return

        completed = self._run_countdown(total_seconds, "Running")
        if completed:
            self.set_countdown("00:00:00")
            def complete():
                if not self._save_session(subject, total_seconds):
                    raise sqlite3.OperationalError("Failed to save session")
            if self._persist_with_retry(complete):
                self.set_status("Completed & saved")
                self._beep()

        self.is_running = False
        self.update_control_state(False, False, False)

    def _wait_for_choice(self):
        if self._progress is not None:
            if not self._persist_with_retry(lambda: self._checkpoint(
                    replace(self._progress, phase="choice", remaining_seconds=0))):
                return None
        with self._command_lock:
            if self.stop_event.is_set():
                return None
            self._choice = None
            self._choice_event.clear()
            self.current_phase = "choice"
            self.set_status("Choose: continue focus or use your break balance")
            self.update_control_state(True, False, False)
        while not self.stop_event.is_set():
            if self._choice_event.wait(0.05):
                with self._command_lock:
                    return None if self.stop_event.is_set() else self._choice
        return None

    def pomodoro_loop(self, subject: str, action="focus", duration=0, return_to_choice=None) -> None:
        if return_to_choice is None:
            return_to_choice = action == "focus"
        try:
            while not self.stop_event.is_set():
                if action == "focus":
                    self.current_phase = "focus"
                    focus_seconds = (self._progress.total_seconds if self._restoring
                                     else config.POMODORO_FOCUS_SECONDS)
                    if not self._prepare_phase("focus", subject, focus_seconds, True):
                        break
                    focus_seconds = self._progress.total_seconds
                    status = f"Pomodoro focus {self.cycle_position + 1}/{config.POMODORO_TOTAL_SESSIONS}"
                    if not self._run_countdown(focus_seconds, status):
                        if self._focus_break_event.is_set() and not self.stop_event.is_set():
                            self._focus_break_event.clear()
                            action, duration = "break", self._progress.total_seconds
                            self._restoring = True
                            continue
                        break
                    def complete_focus():
                        result = complete_pomodoro_focus(subject, focus_seconds, self._progress)
                        self._progress = replace(self._progress, phase="choice", remaining_seconds=0)
                        return result
                    if not self._persist_with_retry(complete_focus):
                        break
                    self.set_status("Focus completed & saved - break balance added")
                    self._beep()
                else:
                    self.current_phase = "break"
                    if not self._prepare_phase("break", subject, duration, return_to_choice):
                        break
                    completed = self._run_countdown(duration, "Using break balance", can_skip_break=True)
                    if self.stop_event.is_set():
                        break
                    if self._progress.suspended_focus is not None:
                        focus = self._progress.suspended_focus
                        if completed:
                            self._beep()
                        if not self._persist_with_retry(lambda: self._checkpoint(focus)):
                            break
                        self.pause_event.set()
                        self._restoring = True
                        action = "focus"
                        continue
                    if completed:
                        destination = "choice" if return_to_choice else "done"
                        if not self._persist_with_retry(lambda: self._checkpoint(
                                replace(self._progress, phase=destination, remaining_seconds=0))):
                            break
                        self._beep()
                        if not return_to_choice:
                            break
                    else:
                        # Skip always offers a next choice, including idle breaks.
                        return_to_choice = True
                if self.stop_event.is_set():
                    break
                choice = self._wait_for_choice()
                if choice is None:
                    break
                action, duration = choice
                return_to_choice = True
        finally:
            with self._command_lock:
                self.is_running = False
                self.current_phase = "manual"
                self.pause_event.clear()
                self.set_status("Pomodoro ready")
                self.update_control_state(False, False, False)

    def _launch(self, target, args, pomodoro=False) -> bool:
        with self._command_lock:
            if self.storage_blocked or self.is_running or (self.timer_thread is not None and self.timer_thread.is_alive()):
                return False
            if pomodoro and not self._load_balance():
                return False
            if pomodoro and len(args) > 1 and args[1] == "break" and args[2] > self.break_balance_seconds:
                return False
            if not pomodoro:
                phase, seconds, subject = "manual", args[0], args[1]
            elif len(args) > 1 and args[1] == "break":
                phase, seconds, subject = "break", args[2], args[0]
            else:
                phase, subject = "focus", args[0]
                seconds = self.focus_seconds_remaining(subject)
                if seconds is None:
                    return False
            progress = ActiveTimer(str(uuid4()), "Pomodoro" if pomodoro else "Manual",
                                   subject, phase, seconds, seconds, phase == "focus")
            try:
                self._checkpoint(progress)
            except (OSError, sqlite3.Error) as error:
                self._storage_error(error)
                return False
            self._restoring = True
            self.stop_event.clear()
            self.pause_event.clear()
            self.skip_break_event.clear()
            self._choice_event.clear()
            self.current_phase = "starting"
            self.is_running = True
            self.timer_thread = threading.Thread(target=target, args=args, daemon=True)
            self.timer_thread.start()
            return True

    def start_timer(self, total_seconds: int, subject: str) -> None:
        if total_seconds > 0:
            self._launch(self.countdown_loop, (total_seconds, subject))

    def start_pomodoro(self, subject: str) -> None:
        self._launch(self.pomodoro_loop, (subject,), pomodoro=True)

    def _submit_choice(self, action, duration=0) -> bool:
        with self._command_lock:
            if self.current_phase != "choice" or self.stop_event.is_set() or self.is_alarm_active:
                return False
            self._choice = (action, duration)
            self.current_phase = "transition"
            self._choice_event.set()
            self.update_control_state(True, False, False)
            return True

    def continue_focus(self) -> bool:
        return self._submit_choice("focus")

    def start_break(self, total_seconds: int, subject: str = "Umum") -> bool:
        with self._command_lock:
            if not isinstance(total_seconds, int) or isinstance(total_seconds, bool) or total_seconds <= 0:
                return False
            paused_focus = self.can_break_paused_focus()
            if self.is_alarm_active or (self.is_running and self.current_phase != "choice" and not paused_focus):
                return False
            if not self._load_balance() or total_seconds > self.break_balance_seconds:
                return False
            if paused_focus:
                focus = self._progress
                progress = ActiveTimer(str(uuid4()), "Pomodoro", focus.subject,
                                       "break", total_seconds, total_seconds, False, focus)
                try:
                    self._checkpoint(progress)
                except (OSError, sqlite3.Error) as error:
                    self._storage_error(error)
                    return False
                self.current_phase = "transition"
                self._focus_break_event.set()
                self.pause_event.clear()
                self.update_control_state(True, False, False)
                return True
            if self.current_phase == "choice":
                return self._submit_choice("break", total_seconds)
            return self._launch(self.pomodoro_loop, (subject, "break", total_seconds), pomodoro=True)

    def can_break_paused_focus(self) -> bool:
        return (self.is_running and self.current_phase == "focus"
                and self.pause_event.is_set() and not self._storage_retry
                and self._progress is not None and self._progress.phase == "focus"
                and self._progress.remaining_seconds > 0)

    def pause_timer(self) -> None:
        if not self.is_running or self.is_alarm_active or self.pause_event.is_set() or self.current_phase not in ("manual", "focus", "break"):
            return
        with self._command_lock:
            self.pause_event.set()
            self._stop_tick()
            try:
                if self._progress is not None:
                    save_active_timer(self._progress)
            except (OSError, sqlite3.Error) as error:
                self._storage_error(error)
        self.set_status("Paused")
        self.update_control_state(started=True, paused=True, can_skip_break=False)

    def resume_timer(self) -> None:
        if not self.is_running or self.is_alarm_active or not self.pause_event.is_set():
            return
        self.pause_event.clear()
        self.set_status("Running")
        can_skip_break = self.current_phase in ("break", "short_break") or (
            self.current_phase == "long_break" and config.POMODORO_ALLOW_SKIP_LONG_BREAK
        )
        self.update_control_state(started=True, paused=False, can_skip_break=can_skip_break)

    def skip_break(self) -> None:
        if not self.is_running or self.is_alarm_active or self.pause_event.is_set():
            return
        if self.current_phase in ("break", "short_break"):
            self.skip_break_event.set()
        elif self.current_phase == "long_break" and config.POMODORO_ALLOW_SKIP_LONG_BREAK:
            self.skip_break_event.set()

    def reset_timer(self) -> bool:
        with self._command_lock:
            if self.storage_blocked:
                return False
            self.pause_event.set()
            self._stop_tick()
            try:
                result = reset_active_timer(self._progress)
                if result is not None:
                    self.break_balance_seconds, self.cycle_position = result
            except (OSError, sqlite3.Error) as error:
                self._storage_error(error)
                self.update_control_state(self.is_running, True)
                return False
            self._progress = None
            self._focus_break_event.clear()
            self._storage_retry = False
            self.stop_event.set()
            self._choice_event.set()
            self.stop_alarm()
            self.pause_event.clear()
            self.skip_break_event.clear()
            self.remaining_seconds = 0
            self.set_status("Ready")
            self.update_control_state(started=False, paused=False, can_skip_break=False)
        if self.timer_thread is not None and self.timer_thread is not threading.current_thread():
            self.timer_thread.join()
        self.is_running = False
        self.current_phase = "manual"
        self.update_control_state(False, False, False)
        return True
