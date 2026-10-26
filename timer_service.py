import sqlite3
import threading
import time
import winsound
from pathlib import Path
from typing import Callable, Optional

import config
from session_repository import (
    save_session, get_pomodoro_state, complete_pomodoro_focus, consume_break_second,
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
        self._load_balance()

    def _load_balance(self) -> bool:
        try:
            self.break_balance_seconds, self.cycle_position = get_pomodoro_state()
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
            with self._command_lock:
                if self.stop_event.is_set():
                    return False
                try:
                    self.break_balance_seconds, self.cycle_position = operation()
                    return True
                except (OSError, sqlite3.Error) as error:
                    self.pause_event.set()
                    self._storage_error(error)
                    self.set_status("Storage error - Resume to retry, or Reset")
                    self.update_control_state(True, True, False)
            while self.pause_event.is_set() and not self.stop_event.wait(0.05):
                pass
        return False

    def _save_session(self, subject: str, total_seconds: int) -> bool:
        try:
            save_session(subject, total_seconds)
        except (OSError, sqlite3.Error) as error:
            message = f"Failed to save session to local database: {error}"
            self.set_status(message)
            if self.on_storage_error is not None:
                self.on_storage_error(message)
            return False
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

    def _run_countdown(
        self,
        total_seconds: int,
        status: str,
        can_skip_break: bool = False,
    ) -> bool:
        self.remaining_seconds = total_seconds
        self.skip_break_event.clear()
        self.update_control_state(True, False, can_skip_break)
        self.set_status(status)

        self.set_countdown(self.format_hms(self.remaining_seconds))
        elapsed = 0.0
        previous = time.monotonic()
        while self.remaining_seconds > 0 and not self.stop_event.is_set():
            if can_skip_break and self.skip_break_event.is_set():
                self.set_countdown("00:00:00")
                return False

            if self.pause_event.is_set():
                self.stop_event.wait(0.05)
                previous = time.monotonic()
                continue
            self.stop_event.wait(0.05)
            now = time.monotonic()
            if self.stop_event.is_set() or self.pause_event.is_set() or self.skip_break_event.is_set():
                previous = now
                continue
            elapsed += now - previous
            previous = now
            if elapsed < 1:
                continue
            # Do not catch up after a suspended machine or slow disk: only a
            # single displayed second can be awaiting its durable debit.
            elapsed = 0.0
            if self.current_phase == "break":
                try:
                    if not self._persist_with_retry(consume_break_second):
                        return False
                except ValueError:
                    self._load_balance()
                    self.set_status("Break balance used by another window")
                    return False
                previous = time.monotonic()
            with self._command_lock:
                if self.stop_event.is_set():
                    return False
                self.remaining_seconds -= 1
                self.set_countdown(self.format_hms(self.remaining_seconds))
                if self.current_phase == "break":
                    self.update_control_state(True, False, can_skip_break)

        return not self.stop_event.is_set() and self.remaining_seconds == 0

    def countdown_loop(self, total_seconds: int, subject: str) -> None:
        self.current_phase = "manual"

        completed = self._run_countdown(total_seconds, "Running")
        if completed:
            self.set_countdown("00:00:00")
            if self._save_session(subject, total_seconds):
                self.set_status("Completed & saved")
            else:
                self.set_status("Completed (save failed)")
            self._beep()

        self.is_running = False
        self.update_control_state(False, False, False)

    def _wait_for_choice(self):
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

    def pomodoro_loop(self, subject: str, action="focus", duration=0) -> None:
        return_to_choice = action == "focus"
        try:
            while not self.stop_event.is_set():
                if action == "focus":
                    self.current_phase = "focus"
                    focus_seconds = config.POMODORO_FOCUS_SECONDS
                    status = f"Pomodoro focus {self.cycle_position + 1}/{config.POMODORO_TOTAL_SESSIONS}"
                    if not self._run_countdown(focus_seconds, status):
                        break
                    if not self._persist_with_retry(
                        lambda: complete_pomodoro_focus(subject, focus_seconds)
                    ):
                        break
                    self.set_status("Focus completed & saved - break balance added")
                    self._beep()
                else:
                    self.current_phase = "break"
                    completed = self._run_countdown(duration, "Using break balance", can_skip_break=True)
                    if self.stop_event.is_set():
                        break
                    if completed:
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
            if self.is_running or (self.timer_thread is not None and self.timer_thread.is_alive()):
                return False
            if pomodoro and not self._load_balance():
                return False
            if pomodoro and len(args) > 1 and args[1] == "break" and args[2] > self.break_balance_seconds:
                return False
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
            if self.is_alarm_active or (self.is_running and self.current_phase != "choice"):
                return False
            if not self._load_balance() or total_seconds > self.break_balance_seconds:
                return False
            if self.current_phase == "choice":
                return self._submit_choice("break", total_seconds)
            return self._launch(self.pomodoro_loop, (subject, "break", total_seconds), pomodoro=True)

    def pause_timer(self) -> None:
        if not self.is_running or self.is_alarm_active or self.pause_event.is_set() or self.current_phase not in ("manual", "focus", "break"):
            return
        self.pause_event.set()
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

    def reset_timer(self) -> None:
        with self._command_lock:
            self.stop_event.set()
            self._choice_event.set()
            self.stop_alarm()
            self.pause_event.clear()
            self.skip_break_event.clear()
            self.remaining_seconds = 0
            self.set_status("Ready")
            self.update_control_state(started=False, paused=False, can_skip_break=False)
