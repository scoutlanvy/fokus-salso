import threading
import time
from types import SimpleNamespace

import customtkinter as ctk

import config
import gui
import session_repository as repository
import timer_service


def test_gui_choices_custom_duration_idle_break_and_ui_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(timer_service.winsound, "PlaySound", lambda *_: None)
    monkeypatch.setattr(timer_service, "time", SimpleNamespace(monotonic=lambda: time.monotonic() * 20))
    repository.complete_pomodoro_focus("Umum", 1500)
    instances = []
    original_countdown = timer_service.TimerService._run_countdown

    class ObservedService(timer_service.TimerService):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

        def _run_countdown(self, *args, **kwargs):
            if self.current_phase == "focus":
                return True
            return original_countdown(self, *args, **kwargs)

    monkeypatch.setattr(gui, "TimerService", ObservedService)
    original_set = ctk.StringVar.set
    ui_thread = threading.get_ident()

    def checked_set(variable, value):
        assert threading.get_ident() == ui_thread, "Tk variable changed from worker"
        return original_set(variable, value)

    monkeypatch.setattr(ctk.StringVar, "set", checked_set)

    def inspect(app):
        service = instances[0]
        errors = []
        closed = False
        app.report_callback_exception = lambda *args: errors.append(args)

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        def widgets():
            return list(descendants(app))

        def button(text, parent=None):
            return next(w for w in descendants(parent or app)
                        if isinstance(w, ctk.CTkButton) and w.cget("text") == text)

        def pump(predicate):
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                app.update()
                if predicate():
                    assert not errors
                    return
                threading.Event().wait(0.005)
            raise AssertionError("GUI did not reach expected state")

        def stopped_alarm_to_choice():
            pump(lambda: button("Stop Alarm").cget("state") == "normal"
                 if any(isinstance(w, ctk.CTkButton) and w.cget("text") == "Stop Alarm" for w in widgets()) else False)
            button("Stop Alarm").invoke()
            pump(lambda: any(isinstance(w, ctk.CTkButton) and w.cget("text") == "Continue Focus" for w in widgets()))

        def dialog():
            button("Choose Duration").invoke()
            app.update()
            return next(w for w in widgets() if isinstance(w, ctk.CTkToplevel))

        def enter_seconds(window, seconds):
            entries = [w for w in descendants(window) if isinstance(w, ctk.CTkEntry)]
            entries[2].delete(0, "end")
            entries[2].insert(0, str(seconds))

        try:
            app.update()
            subject = next(w for w in widgets() if isinstance(w, ctk.CTkOptionMenu) and "Umum" in w.cget("values"))
            assert subject.get() == "Umum"
            mode = next(w for w in widgets() if isinstance(w, ctk.CTkOptionMenu) and "Pomodoro" in w.cget("values"))
            assert mode.get() == "Pomodoro"
            assert not service.is_running
            assert button("Start").cget("state") == "normal"
            app.focus_force()
            app.event_generate("<KeyPress-space>")
            app.event_generate("<KeyRelease-space>")
            assert not service.is_running
            def displayed(value):
                return any(isinstance(w, ctk.CTkLabel)
                           and str(w.cget("textvariable"))
                           and app.getvar(str(w.cget("textvariable"))) == value
                           for w in widgets())

            assert displayed("00:25:00")
            mode.set("Manual")
            mode.cget("command")("Manual")
            app.update()
            assert mode.get() == "Manual"
            assert displayed("00:00:00")
            assert not service.is_running
            mode.set("Pomodoro")
            mode.cget("command")("Pomodoro")
            app.update()
            assert button("Break 5 min").cget("state") == "normal"
            window = dialog()
            button("Start Break", window).invoke()  # Zero rejected.
            assert window.winfo_exists()
            entries = [w for w in descendants(window) if isinstance(w, ctk.CTkEntry)]
            entries[0].delete(0, "end")
            entries[0].insert(0, "1")  # Greater than the available five minutes.
            button("Start Break", window).invoke()
            assert not service.is_running
            button("Cancel", window).invoke()
            assert repository.get_pomodoro_state() == (300, 1)

            button("Start").invoke()
            stopped_alarm_to_choice()
            assert button("Break 10 min").cget("state") == "normal"
            button("Continue Focus").invoke()
            stopped_alarm_to_choice()
            assert service.break_balance_seconds == 900
            window = dialog()
            enter_seconds(window, 1)
            button("Start Break", window).invoke()
            stopped_alarm_to_choice()
            assert repository.get_pomodoro_state() == (899, 3)

            # Use all remaining balance, then interrupt it without losing the rest.
            next(w for w in widgets() if isinstance(w, ctk.CTkButton)
                 and w.cget("text").startswith("Break ")).invoke()
            pump(lambda: service.current_phase == "break")
            pump(lambda: button("Skip Break").cget("state") == "normal")
            app.focus_force()
            app.event_generate("<KeyPress-space>")
            assert service.pause_event.is_set()
            app.event_generate("<KeyPress-space>")
            assert service.pause_event.is_set()  # Holding Space cannot resume.
            app.event_generate("<KeyRelease-space>")
            app.event_generate("<KeyPress-space>")
            assert not service.pause_event.is_set()
            app.event_generate("<KeyRelease-space>")
            button("Skip Break").invoke()
            pump(lambda: service.current_phase == "choice")
            button("Reset").invoke()
            pump(lambda: not service.is_running)
            saved = repository.get_pomodoro_state()
            assert saved[0] > 0
            assert saved[1] == 3

            # A custom break from idle finishes back at idle after acknowledgement.
            pump(lambda: button("Choose Duration").cget("state") == "normal")
            window = dialog()
            enter_seconds(window, 1)
            button("Start Break", window).invoke()
            pump(lambda: service.is_alarm_active)
            pump(lambda: any(isinstance(w, ctk.CTkButton) and w.cget("text") == "Stop Alarm" for w in widgets()))
            button("Stop Alarm").invoke()
            pump(lambda: not service.is_running)
            assert repository.get_pomodoro_state() == (saved[0] - 1, 3)
            assert len(repository.get_recent_sessions()) == 3
            assert not errors
            pump(lambda: any(isinstance(w, ctk.CTkButton) and w.cget("text") == "Start" for w in widgets()))
            button("Start").invoke()
            stopped_alarm_to_choice()
            before_close = repository.get_pomodoro_state()
            app.tk.call(app.protocol("WM_DELETE_WINDOW"))
            closed = True
            service.timer_thread.join(2)
            assert not service.timer_thread.is_alive()
            reopened = timer_service.TimerService(lambda _: None, lambda _: None, lambda *_, **__: None)
            assert (reopened.break_balance_seconds, reopened.cycle_position) == before_close
            assert not reopened.is_running
        finally:
            service.reset_timer()
            if service.timer_thread:
                service.timer_thread.join(2)
            if not closed:
                app.destroy()

    monkeypatch.setattr(ctk.CTk, "mainloop", inspect)
    gui.run_app()
