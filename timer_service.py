import sqlite3
import threading
import time
import winsound
from typing import Callable, Optional

import config
from session_repository import save_session

Callback = Callable[[str], None]
ControlStateCallback = Callable[[bool, bool, bool], None]


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
        self.remaining_seconds = 0
        self.is_running = False
        self.current_phase = "manual"

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
        for _ in range(3):
            winsound.Beep(1000, 700)

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

        while self.remaining_seconds >= 0 and not self.stop_event.is_set():
            if can_skip_break and self.skip_break_event.is_set():
                self.set_countdown("00:00:00")
                return False

            if self.pause_event.is_set():
                self.set_status("Paused")
                time.sleep(0.2)
                continue

            self.set_countdown(self.format_hms(self.remaining_seconds))
            time.sleep(1)
            self.remaining_seconds -= 1

        return not self.stop_event.is_set() and self.remaining_seconds < 0

    def countdown_loop(self, total_seconds: int, subject: str) -> None:
        self.stop_event.clear()
        self.pause_event.clear()
        self.skip_break_event.clear()
        self.is_running = True
        self.current_phase = "manual"

        completed = self._run_countdown(total_seconds, "Running")
        if completed:
            self.set_countdown("00:00:00")
            self._beep()
            if self._save_session(subject, total_seconds):
                self.set_status("Completed & saved")
            else:
                self.set_status("Completed (save failed)")

        self.is_running = False
        self.update_control_state(False, False, False)

    def pomodoro_loop(self, subject: str) -> None:
        self.stop_event.clear()
        self.pause_event.clear()
        self.skip_break_event.clear()
        self.is_running = True

        focus_seconds = config.POMODORO_FOCUS_MINUTES * 60
        short_break_seconds = config.POMODORO_SHORT_BREAK_MINUTES * 60
        long_break_seconds = config.POMODORO_LONG_BREAK_MINUTES * 60

        for session in range(1, config.POMODORO_TOTAL_SESSIONS + 1):
            self.current_phase = "focus"
            focus_status = f"Pomodoro session {session}/{config.POMODORO_TOTAL_SESSIONS} - Focus"
            if not self._run_countdown(focus_seconds, focus_status):
                break

            self.set_countdown("00:00:00")
            self._beep()
            if self._save_session(subject, focus_seconds):
                self.set_status(f"Session {session} completed & saved")
            else:
                self.set_status(f"Session {session} completed (save failed)")

            if session < config.POMODORO_TOTAL_SESSIONS:
                self.current_phase = "short_break"
                break_status = f"Break session {session} - {config.POMODORO_SHORT_BREAK_MINUTES} min"
                break_completed = self._run_countdown(
                    short_break_seconds,
                    break_status,
                    can_skip_break=True,
                )
                if self.stop_event.is_set():
                    break
                if break_completed:
                    self._beep()
                else:
                    self.set_status(f"Break session {session} skipped")
            else:
                self.current_phase = "long_break"
                long_break_status = f"Long break - {config.POMODORO_LONG_BREAK_MINUTES} min"
                long_break_completed = self._run_countdown(
                    long_break_seconds,
                    long_break_status,
                    can_skip_break=config.POMODORO_ALLOW_SKIP_LONG_BREAK,
                )
                if long_break_completed:
                    self._beep()

        self.is_running = False
        self.current_phase = "manual"
        if self.stop_event.is_set():
            self.set_status("Ready")
        else:
            self.set_countdown("00:00:00")
            self.set_status("Pomodoro completed")
        self.update_control_state(False, False, False)

    def start_timer(self, total_seconds: int, subject: str) -> None:
        if self.is_running:
            return

        self.timer_thread = threading.Thread(
            target=self.countdown_loop,
            args=(total_seconds, subject),
            daemon=True
        )
        self.timer_thread.start()

    def start_pomodoro(self, subject: str) -> None:
        if self.is_running:
            return

        self.timer_thread = threading.Thread(
            target=self.pomodoro_loop,
            args=(subject,),
            daemon=True
        )
        self.timer_thread.start()

    def pause_timer(self) -> None:
        if not self.is_running or self.pause_event.is_set():
            return
        self.pause_event.set()
        self.set_status("Paused")
        self.update_control_state(started=True, paused=True, can_skip_break=False)

    def resume_timer(self) -> None:
        if not self.is_running or not self.pause_event.is_set():
            return
        self.pause_event.clear()
        self.set_status("Running")
        can_skip_break = self.current_phase == "short_break" or (
            self.current_phase == "long_break" and config.POMODORO_ALLOW_SKIP_LONG_BREAK
        )
        self.update_control_state(started=True, paused=False, can_skip_break=can_skip_break)

    def skip_break(self) -> None:
        if not self.is_running:
            return
        if self.current_phase == "short_break":
            self.skip_break_event.set()
        elif self.current_phase == "long_break" and config.POMODORO_ALLOW_SKIP_LONG_BREAK:
            self.skip_break_event.set()

    def reset_timer(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        self.skip_break_event.clear()
        self.is_running = False
        self.remaining_seconds = 0
        self.current_phase = "manual"
        self.set_status("Ready")
        self.update_control_state(started=False, paused=False, can_skip_break=False)
