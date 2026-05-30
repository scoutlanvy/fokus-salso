import threading
import time
import winsound
from typing import Callable, Optional

from notion_service import save_session_to_notion

Callback = Callable[[str], None]
ControlStateCallback = Callable[[bool, bool], None]


class TimerService:
    def __init__(self, set_countdown: Callback, set_status: Callback, update_control_state: ControlStateCallback):
        self.set_countdown = set_countdown
        self.set_status = set_status
        self.update_control_state = update_control_state
        self.timer_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.remaining_seconds = 0
        self.is_running = False

    def format_hms(self, total_seconds: int) -> str:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def countdown_loop(self, total_seconds: int, subject: str) -> None:
        self.remaining_seconds = total_seconds
        self.stop_event.clear()
        self.pause_event.clear()
        self.is_running = True

        self.update_control_state(started=True)
        self.set_status("Countdown berjalan")

        while self.remaining_seconds >= 0 and not self.stop_event.is_set():
            if self.pause_event.is_set():
                self.set_status("Paused")
                time.sleep(0.2)
                continue

            self.set_countdown(self.format_hms(self.remaining_seconds))
            time.sleep(1)
            self.remaining_seconds -= 1

        if self.stop_event.is_set():
            return

        if self.remaining_seconds < 0:
            self.set_countdown("00:00:00")
            self.set_status("Selesai")
            self.is_running = False
            self.update_control_state(started=False, paused=False)

            for _ in range(3):
                winsound.Beep(1000, 700)

            save_session_to_notion(subject, total_seconds)
            self.set_status("Selesai dan tersimpan")

    def start_timer(self, total_seconds: int, subject: str) -> None:
        if self.is_running:
            return

        self.timer_thread = threading.Thread(
            target=self.countdown_loop,
            args=(total_seconds, subject),
            daemon=True
        )
        self.timer_thread.start()

    def pause_timer(self) -> None:
        if not self.is_running or self.pause_event.is_set():
            return
        self.pause_event.set()
        self.set_status("Paused")
        self.update_control_state(started=True, paused=True)

    def resume_timer(self) -> None:
        if not self.is_running or not self.pause_event.is_set():
            return
        self.pause_event.clear()
        self.set_status("Countdown berjalan")
        self.update_control_state(started=True, paused=False)

    def reset_timer(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        self.is_running = False
        self.remaining_seconds = 0
        self.set_status("Ready")
        self.update_control_state(started=False, paused=False)
