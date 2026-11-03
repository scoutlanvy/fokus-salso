import threading
import ctypes
import time
from tkinter import Menu
from types import SimpleNamespace

import customtkinter as ctk

from study_timer import config
from study_timer.ui import main_window as gui
from study_timer.app import run_app
from study_timer import session_repository as repository
from study_timer import audio
from study_timer import timer_service
from study_timer import subject_store


def test_subject_popup_scaled_rows_and_mouse_selection():
    app = ctk.CTk()
    app.geometry("700x700+20+20")
    context_calls = []

    def check_scale(scale):
        ctk.set_widget_scaling(scale)
        subject = gui.SubjectOptionMenu(
            app, values=config.SUBJECT_OPTIONS,
            context_command=lambda *args: context_calls.append(args))
        subject.pack()
        app.update()
        subject._text_label.event_generate("<Button-1>", x=10, y=10)
        app.update()
        popup = subject.subject_popup
        assert popup is not None
        # A short list must fit in full at every supported widget scale.
        for row in subject.subject_rows.values():
            assert row.winfo_rooty() >= popup.winfo_rooty()
            assert row.winfo_rooty() + row.winfo_height() <= popup.winfo_rooty() + popup.winfo_height()
        english = subject.subject_rows["English"]._text_label
        english.event_generate("<Enter>")
        english.event_generate("<Button-1>", x=5, y=5)
        english.event_generate("<ButtonRelease-1>", x=5, y=5)
        app.update()
        assert subject.get() == "English"
        assert subject.subject_popup is None
        subject._open_dropdown_menu()
        app.update()
        subject.subject_rows["Anki"]._text_label.event_generate("<Button-3>", x=5, y=5)
        app.update()
        assert context_calls[-1][0] == "Anki"
        assert subject.get() == "English"
        assert subject.subject_popup is not None
        subject.close_subject_popup()
        subject.destroy()

    try:
        for scale in (1.0, 1.5, 2.0):
            check_scale(scale)
    finally:
        app.destroy()
        ctk.set_widget_scaling(1.0)


def test_subject_native_context_menu_lifecycle():
    app = ctk.CTk()
    app.geometry("700x700+20+20")
    errors, confirmations = [], []
    app.report_callback_exception = lambda *args: errors.append(args)
    menu = Menu(app, tearoff=False)
    subject = gui.SubjectOptionMenu(app, values=config.SUBJECT_OPTIONS, context_command=lambda *_: None)
    subject.pack()

    def open_subject():
        subject._open_dropdown_menu()
        app.update()
        return subject.subject_popup

    def delete():
        subject.close_subject_popup()
        confirmations.append(subject.subject_popup)

    menu.add_command(label="Hapus", command=delete)

    def native_key(key):
        # Target only this GUI thread's native menu window, never global input.
        thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        sent = []

        def send():
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            @callback_type
            def visit(hwnd, _):
                name = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(ctypes.c_void_p(hwnd), name, 256)
                if name.value == "#32768":
                    if key in ("outside", "list"):
                        position = (2000 << 16) | 2000 if key == "outside" else (5 << 16) | (0xffff & -20)
                        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x201, 1, position)
                        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x202, 0, position)
                        sent.append(True)
                        return True
                    if key == 0x0D:
                        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x100, 0x28, 0)
                        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x101, 0x28, 0)
                    ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x100, key, 0)
                    ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x101, key, 0)
                    sent.append(True)
                return True

            deadline = time.monotonic() + 5
            while not sent and time.monotonic() < deadline:
                ctypes.windll.user32.EnumThreadWindows(thread_id, visit, 0)
                time.sleep(0.01)

        worker = threading.Thread(target=send)
        worker.start()
        return worker, sent

    try:
        for scale in (1.0, 1.5, 2.0):
            ctk.set_widget_scaling(scale)
            app.update()
            popup = open_subject()
            x, y = popup.winfo_rootx() + popup.winfo_width(), popup.winfo_rooty()

            worker, sent = native_key(0x1B)
            subject.post_context_menu(menu, x, y)
            worker.join(6)
            assert sent
            app.update()
            assert subject.subject_popup == popup
            assert subject.context_menu is None
            assert app.grab_current() == popup
            assert app.focus_get().winfo_toplevel() == popup

            worker, sent = native_key("list")
            subject.post_context_menu(menu, x, y)
            worker.join(6)
            app.update()
            assert sent
            assert subject.subject_popup == popup
            assert app.grab_current() == popup

            worker, sent = native_key("outside")
            subject.post_context_menu(menu, x, y)
            worker.join(6)
            app.update()
            assert subject.subject_popup is None

            popup = open_subject()
            worker, sent = native_key(0x0D)
            subject.post_context_menu(menu, x, y)
            worker.join(6)
            app.update()
            assert subject.subject_popup is None
            assert confirmations[-1] is None
            assert subject.get() == "Umum"
        assert not errors
    finally:
        subject.close_subject_popup()
        app.destroy()
        ctk.set_widget_scaling(1.0)


def test_gui_delete_subject(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(audio.winsound, "PlaySound", lambda *_: None)
    repository.reset_active_timer(repository.ActiveTimer(
        "partial-english", "Pomodoro", "English", "focus", 1500, 900, True))
    history = repository.get_summary_by_subject()
    confirmations, errors, services = [], [], []
    controls = []
    accept = False
    original_service = gui.TimerService

    def service_factory(*args, **kwargs):
        service = original_service(*args, **kwargs)
        services.append(service)
        return service

    def confirm(*args, **kwargs):
        assert controls[0].subject_popup is None
        confirmations.append(args)
        return accept

    monkeypatch.setattr(gui, "TimerService", service_factory)
    monkeypatch.setattr(gui.messagebox, "askyesno", confirm)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))

    def inspect(app):
        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)

        def button(text):
            return next(w for w in descendants(app)
                        if isinstance(w, ctk.CTkButton) and w.cget("text") == text)

        nonlocal accept
        try:
            app.update()
            subject = next(w for w in descendants(app) if isinstance(w, ctk.CTkOptionMenu)
                           and "Umum" in w.cget("values"))
            controls.append(subject)
            # Dispatch through Tk bindtags, including CTk's global click-focus handler.
            # Calling _open_dropdown_menu directly misses the real left-click race.
            for surface in (subject._text_label, subject._canvas):
                surface.event_generate("<Button-1>", x=10, y=10)
                app.update()
                assert subject.subject_popup is not None
                assert subject.subject_rows["English"].winfo_viewable()
                assert subject.subject_rows["English"].winfo_width() > 1
                assert app.focus_get().winfo_toplevel() == subject.subject_popup
                subject.close_subject_popup()
            delete = button("−")
            assert delete.cget("state") == "disabled"
            context = next(w for w in app.winfo_children() if isinstance(w, Menu))
            # Avoid entering Windows' native menu modal loop in this callback test.
            posted = []
            monkeypatch.setattr(context, "tk_popup", lambda x, y: posted.append((x, y)))

            def right_click(name):
                subject._open_dropdown_menu()
                app.update()
                assert subject.subject_popup is not None or subject.cget("state") == "disabled", app.focus_get()
                if subject.subject_popup is not None:
                    subject.subject_rows[name]._canvas.event_generate("<Button-3>", x=12, y=10)
                app.update()

            # A different item is the target; merely opening/cancelling keeps selection.
            right_click("English")
            assert subject.get() == "Umum"
            assert posted
            assert subject.subject_popup is not None
            assert context.entrycget(0, "label") == "Hapus"
            context.invoke(0)
            context.unpost()
            assert subject.get() == "Umum"
            assert "English" in confirmations[-1][1]
            right_click("Umum")
            assert context.entrycget(0, "state") == "disabled"
            context.unpost()
            subject._open_dropdown_menu()
            app.update()
            subject.subject_popup.event_generate("<Button-3>", x=0, y=0)
            assert not context.winfo_ismapped()
            subject.subject_popup.event_generate("<Escape>")
            assert subject.subject_popup is None
            subject._open_dropdown_menu()
            app.update()
            subject.subject_popup.event_generate("<Button-1>", x=-5, y=-5)
            assert subject.subject_popup is None
            subject._open_dropdown_menu()
            app.update()
            app.focus_force()
            app.update()
            assert subject.subject_popup is None
            subject.set("English")
            assert delete.cget("state") == "normal"
            delete.invoke()
            assert subject.get() == "English"
            assert "English" in confirmations[-1][1]
            accept = True
            original_delete = subject_store.delete_subject

            def fail(_):
                raise OSError("save failed")

            monkeypatch.setattr(subject_store, "delete_subject", fail)
            right_click("English")
            context.invoke(0)
            context.unpost()
            assert errors and subject.get() == "English"
            assert "English" in subject.cget("values")
            monkeypatch.setattr(subject_store, "delete_subject", original_delete)
            subject.set("Linux")
            right_click("English")
            context.invoke(0)
            context.unpost()
            assert subject.get() == "Umum"
            assert "English" not in subject.cget("values")
            assert delete.cget("state") == "disabled"
            assert repository.get_summary_by_subject() == history
            # Left-click command still selects normally after a context action.
            subject._open_dropdown_menu()
            app.update()
            subject.subject_rows["Anki"].invoke()
            assert subject.get() == "Anki"
            subject_store.add_subject("English")
            subject.set("English")
            assert any(isinstance(w, ctk.CTkLabel)
                       and w.cget("text") == "Target progress: 00:10:00 / 00:25:00"
                       for w in descendants(app))
            button("Start").invoke()
            assert delete.cget("state") == "disabled"
            posted_before = len(posted)
            right_click("Anki")
            assert len(posted) == posted_before
            assert not context.winfo_ismapped()
            subject.close_subject_popup()
            button("Pause").invoke()
            assert delete.cget("state") == "disabled"
            right_click("Anki")
            assert len(posted) == posted_before
            assert not context.winfo_ismapped()
            subject.close_subject_popup()
            button("Reset").invoke()
            assert delete.cget("state") == "normal"
            services[0].storage_blocked = True
            subject.set("Anki")
            assert delete.cget("state") == "disabled"
            right_click("Anki")
            assert len(posted) == posted_before
            assert not context.winfo_ismapped()
            subject.close_subject_popup()
            services[0].storage_blocked = False
        finally:
            app.tk.call(app.protocol("WM_DELETE_WINDOW"))

    monkeypatch.setattr(ctk.CTk, "mainloop", inspect)
    run_app()


def test_gui_choices_custom_duration_idle_break_and_ui_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(audio.winsound, "PlaySound", lambda *_: None)
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
            history = next(w for w in widgets() if isinstance(w, gui.HistoryPanel))
            assert not history.winfo_ismapped()
            toggle = button("Show History")
            timer_content = toggle.master.master
            timer_controls = button("Start").master

            def timer_widths():
                # The cards must follow the visible canvas, not just its outer grid column.
                assert abs(timer_content.winfo_width() - timer_content.master.winfo_width()) <= 1
                assert timer_controls.winfo_width() >= timer_content.winfo_width() - 60
                return timer_content.winfo_width(), timer_controls.winfo_width()

            for size in ("1100x700", "900x620", "1100x700"):
                app.geometry(size)
                app.update()
                hidden_widths = timer_widths()
                toggle.invoke()
                app.update()
                assert history.winfo_ismapped()
                assert toggle.cget("text") == "Hide History"
                shown_widths = timer_widths()
                assert all(hidden > shown for hidden, shown in zip(hidden_widths, shown_widths))
                history.tabview.set("Recent Sessions")
                toggle.invoke()
                app.update()
                assert not history.winfo_ismapped()
                assert timer_widths() == hidden_widths
                layout = history.master.master
                assert layout.grid_bbox(column=1, row=0)[2] == 0
            toggle.invoke()
            app.update()
            assert history.tabview.get() == "Recent Sessions"
            history.tabview.set("Summary")
            toggle.invoke()
            subject = next(w for w in widgets() if isinstance(w, ctk.CTkOptionMenu) and "Umum" in w.cget("values"))
            assert subject.get() == "Umum"
            monkeypatch.setattr(ctk, "CTkInputDialog", lambda **kwargs: SimpleNamespace(get_input=lambda: "  Matematika  "))
            button("+").invoke()
            assert subject.get() == "Matematika"
            assert "Matematika" in subject.cget("values")
            assert gui.subject_store.load_subjects()[-1] == "Matematika"
            subject.set("Umum")
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
            toggle.invoke()
            app.update()
            assert history.winfo_ismapped()
            assert any(isinstance(w, ctk.CTkLabel) and w.cget("text") == "50m (2 sessions)"
                       for w in descendants(history.summary_scroll))
            toggle.invoke()
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
            toggle.invoke()
            toggle.invoke()
            assert service.is_running
            assert service.current_phase == "break"
            assert subject.get() == "Umum"
            app.focus_force()
            app.event_generate("<KeyPress-space>")
            assert service.pause_event.is_set()
            paused_remaining = service.remaining_seconds
            toggle.invoke()
            toggle.invoke()
            assert service.pause_event.is_set()
            assert service.remaining_seconds == paused_remaining
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
    run_app()


def test_gui_subject_accumulation_and_read_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "sessions.sqlite3")
    monkeypatch.setattr(audio.winsound, "PlaySound", lambda *_: None)
    repository.reset_active_timer(repository.ActiveTimer(
        "partial-umum", "Pomodoro", "Umum", "focus", 1500, 607, True))
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))

    def inspect(app):
        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)

        def button(text):
            return next(w for w in descendants(app)
                        if isinstance(w, ctk.CTkButton) and w.cget("text") == text)

        def displayed(value):
            return any(isinstance(w, ctk.CTkLabel) and str(w.cget("textvariable"))
                       and app.getvar(str(w.cget("textvariable"))) == value
                       for w in descendants(app))

        def target(value):
            return any(isinstance(w, ctk.CTkLabel) and w.cget("text") == value
                       for w in descendants(app))

        try:
            app.update()
            subject = next(w for w in descendants(app) if isinstance(w, ctk.CTkOptionMenu)
                           and "Umum" in w.cget("values"))
            assert displayed("00:10:07")
            assert target("Target progress: 00:14:53 / 00:25:00")
            button("Reset").invoke()
            assert displayed("00:10:07")
            subject.set("English")
            assert displayed("00:10:07")
            subject.set("Umum")
            assert displayed("00:10:07")
            mode = next(w for w in descendants(app) if isinstance(w, ctk.CTkOptionMenu)
                        and "Manual" in w.cget("values"))
            mode.cget("command")("Manual")
            assert displayed("00:00:00")
            mode.cget("command")("Pomodoro")
            assert displayed("00:10:07")
            original_read = timer_service.get_focus_progress

            def fail(_):
                raise repository.sqlite3.OperationalError("read failure")

            monkeypatch.setattr(timer_service, "get_focus_progress", fail)
            subject.set("English")
            assert displayed("--:--:--")
            assert button("Retry").cget("state") == "normal"
            assert repository.load_active_timer() is None
            monkeypatch.setattr(timer_service, "get_focus_progress", original_read)
            button("Retry").invoke()
            assert button("Start").cget("state") == "normal"
            assert displayed("00:10:07")
            subject.set("Umum")
            assert displayed("00:10:07")
            assert repository.get_summary_by_subject() == [("Umum", 893, 1)]
        finally:
            app.tk.call(app.protocol("WM_DELETE_WINDOW"))

    monkeypatch.setattr(ctk.CTk, "mainloop", inspect)
    run_app()
