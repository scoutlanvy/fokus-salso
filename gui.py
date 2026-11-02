import customtkinter as ctk
import queue
import sqlite3
import sys
from contextlib import contextmanager
from tkinter import Menu, Toplevel, messagebox

import config
from duration_picker import DurationPicker
from history_panel import HistoryPanel
from timer_service import TimerService
from instance_lock import InstanceLock, AlreadyRunningError
import subject_store


class SubjectOptionMenu(ctk.CTkOptionMenu):
    """Use Tk widgets for subject rows so Windows delivers right-click events."""

    def __init__(self, *args, context_command, **kwargs):
        super().__init__(*args, **kwargs)
        self.context_command = context_command
        self.subject_popup = None
        self.subject_rows = {}
        self.context_menu = None
        self._restore_subject_popup = True

    def close_subject_popup(self):
        if self.context_menu is not None:
            menu, self.context_menu = self.context_menu, None
            menu.unpost()
            menu.grab_release()
        if self.subject_popup is not None:
            self.subject_popup.grab_release()
            self.subject_popup.destroy()
            self.subject_popup = None
            self.subject_rows = {}

    def _clicked(self, event=None):
        if self.subject_popup is not None:
            self.close_subject_popup()
        elif self.cget("state") != ctk.DISABLED:
            # CTk's global Button-1 handler focuses the clicked control. Wait for
            # that handler before moving focus into the popup, or FocusOut closes it.
            self.after_idle(self._open_dropdown_menu)

    def _open_dropdown_menu(self):
        if self.cget("state") == ctk.DISABLED:
            return
        self.close_subject_popup()
        popup = self.subject_popup = Toplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())
        width = max(self.winfo_width(), 220)
        height = round(self._apply_widget_scaling(min(300, len(self.cget("values")) * 36 + 12)))
        x = min(self.winfo_rootx(), self.winfo_screenwidth() - width)
        y = self.winfo_rooty() + self.winfo_height()
        if y + height > self.winfo_screenheight():
            y = max(0, self.winfo_rooty() - height)
        popup.geometry(f"{width}x{height}+{max(0, x)}+{y}")
        rows = ctk.CTkScrollableFrame(popup, corner_radius=0)
        rows.pack(fill="both", expand=True)
        for name in self.cget("values"):
            row = ctk.CTkButton(
                rows, text=name, anchor="w", height=30, fg_color="transparent",
                command=lambda name=name: self._select_subject(name),
            )
            row.pack(fill="x", pady=2)
            row.bind("<Button-3>", lambda event, name=name: self._context_subject(event, name))
            self.subject_rows[name] = row
        popup.bind("<Escape>", lambda event: self.close_subject_popup())
        popup.bind("<Button-1>", self._outside_subject_popup)
        popup.bind("<FocusOut>", lambda event: self.after_idle(self._check_popup_focus))
        popup.deiconify()
        popup.update_idletasks()
        popup.grab_set()
        popup.focus_force()

    def _outside_subject_popup(self, event):
        popup = self.subject_popup
        if popup is not None and not (
            popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
            and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()
        ):
            self.close_subject_popup()
            return "break"

    def _check_popup_focus(self):
        if self.context_menu is not None:
            return
        popup = self.subject_popup
        if popup is not None:
            focus = self.focus_get()
            if focus is None or focus.winfo_toplevel() != popup:
                self.close_subject_popup()

    def _select_subject(self, name):
        self.close_subject_popup()
        self._dropdown_callback(name)

    def _context_subject(self, event, name):
        row = self.subject_rows[name]
        x, y = row.winfo_rootx() + row.winfo_width(), row.winfo_rooty()
        self.context_command(name, x, y)
        return "break"

    def post_context_menu(self, menu, x, y):
        self.context_menu = menu
        self._restore_subject_popup = True
        self.subject_popup.grab_release()
        menu.bind("<Unmap>", lambda event: self.after_idle(lambda: self._finish_context_menu(menu)))
        menu.bind("<Escape>", self._cancel_context_menu)
        menu.bind("<ButtonPress-1>", self._context_menu_click)
        try:
            with self._native_context_dismissal():
                menu.tk_popup(x, y)
        finally:
            menu.grab_release()
            if not menu.winfo_ismapped():
                self._finish_context_menu(menu)

    @contextmanager
    def _native_context_dismissal(self):
        """Native Windows menus consume outside clicks before Tk bindings see them."""
        if sys.platform != "win32":
            yield
            return
        import ctypes
        from ctypes import wintypes

        popup = self.subject_popup
        bounds = (popup.winfo_rootx(), popup.winfo_rooty(),
                  popup.winfo_rootx() + popup.winfo_width(),
                  popup.winfo_rooty() + popup.winfo_height())
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = wintypes.LPARAM
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

        @callback_type
        def watch(code, wparam, lparam):
            if code == 2:  # MSGF_MENU, limited to this thread's menu modal loop.
                message = ctypes.cast(lparam, ctypes.POINTER(wintypes.MSG)).contents
                if message.message in (0x201, 0x204):  # left/right mouse down
                    point = wintypes.POINT(ctypes.c_short(message.lParam & 0xffff).value,
                                           ctypes.c_short((message.lParam >> 16) & 0xffff).value)
                    user32.ClientToScreen(message.hWnd, ctypes.byref(point))
                    rect = wintypes.RECT()
                    user32.GetWindowRect(message.hWnd, ctypes.byref(rect))
                    in_menu = rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom
                    in_list = bounds[0] <= point.x < bounds[2] and bounds[1] <= point.y < bounds[3]
                    self._restore_subject_popup = in_menu or in_list
                elif message.message == 0x100 and message.wParam == 0x1B:
                    self._restore_subject_popup = True
            return user32.CallNextHookEx(None, code, wparam, lparam)

        hook = user32.SetWindowsHookExW(-1, watch, None, ctypes.windll.kernel32.GetCurrentThreadId())
        try:
            yield
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)

    def _cancel_context_menu(self, event):
        self._restore_subject_popup = True
        if self.context_menu is not None:
            self.context_menu.unpost()
        return "break"

    def _context_menu_click(self, event):
        menu = self.context_menu
        if menu is not None and not (
            menu.winfo_rootx() <= event.x_root < menu.winfo_rootx() + menu.winfo_width()
            and menu.winfo_rooty() <= event.y_root < menu.winfo_rooty() + menu.winfo_height()
        ):
            popup = self.subject_popup
            self._restore_subject_popup = popup is not None and (
                popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
                and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()
            )
            menu.unpost()
            return "break"

    def _finish_context_menu(self, menu):
        if self.context_menu != menu:
            return
        self.context_menu = None
        if self.subject_popup is not None:
            if self._restore_subject_popup and self.cget("state") != ctk.DISABLED:
                self.subject_popup.grab_set()
                self.subject_popup.focus_force()
            else:
                self.close_subject_popup()


def run_app() -> None:
    try:
        with InstanceLock(config.DATABASE_PATH):
            _run_app()
    except (AlreadyRunningError, OSError) as error:
        root = ctk.CTk()
        root.iconbitmap(default=str(config.APP_ICON))
        root.withdraw()
        try:
            messagebox.showerror(config.APP_TITLE, str(error), parent=root)
        finally:
            root.destroy()


def _run_app() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.iconbitmap(default=str(config.APP_ICON))
    app.title(config.APP_TITLE)
    app.geometry(config.WINDOW_SIZE)
    app.resizable(config.WINDOW_RESIZABLE, config.WINDOW_RESIZABLE)

    selected_subject = ctk.StringVar(value=config.SUBJECT_OPTIONS[0])
    selected_mode = ctk.StringVar(value="Pomodoro")
    status_var = ctk.StringVar(value="Ready")
    countdown_var = ctk.StringVar(
        value=f"{config.DEFAULT_HOURS:02}:{config.DEFAULT_MINUTES:02}:{config.DEFAULT_SECONDS:02}"
    )

    duration_picker = None
    history_panel = None
    closing = False
    ui_events = queue.Queue()
    duration_dialog = None
    settings_dialog = None
    settings_controls = []

    def set_countdown(value: str) -> None:
        if closing:
            return
        countdown_var.set(value)
        if selected_mode.get() == "Pomodoro":
            refresh_focus_target(update_idle_timer=False)

    def set_status(value: str) -> None:
        if closing:
            return
        status_var.set(value)
        if history_panel is not None and ("saved" in value.lower() or "completed" in value.lower()):
            app.after(100, history_panel.refresh)

    def update_control_state(
        started: bool,
        paused: bool = False,
        can_skip_break: bool = False,
    ) -> None:
        if closing:
            return
        started = timer_service.is_running
        paused = timer_service.pause_event.is_set()
        choosing = started and timer_service.current_phase == "choice"
        if timer_service.is_alarm_active:
            primary_button.configure(text="Stop Alarm", command=timer_service.stop_alarm)
        elif choosing:
            primary_button.configure(text="Continue Focus", command=timer_service.continue_focus)
        elif not started:
            primary_button.configure(text="Start", command=start_timer)
        elif paused:
            primary_button.configure(text="Resume", command=resume_timer)
        else:
            primary_button.configure(text="Pause", command=pause_timer)
        primary_button.configure(state=ctk.DISABLED if timer_service.current_phase in ("transition", "starting") else ctk.NORMAL)
        reset_button.configure(state=ctk.NORMAL)
        can_skip = timer_service.current_phase == "break" and not paused and not timer_service.is_alarm_active
        skip_break_button.configure(state=ctk.NORMAL if can_skip else ctk.DISABLED)
        if started and timer_service.current_phase == "break":
            skip_break_button.grid()
        else:
            skip_break_button.grid_remove()
        mode_menu.configure(state=ctk.DISABLED if started else ctk.NORMAL)
        subject_menu.configure(state=ctk.DISABLED if started else ctk.NORMAL)
        add_subject_button.configure(state=ctk.DISABLED if started else ctk.NORMAL)
        delete_subject_button.configure(
            state=ctk.DISABLED if started or selected_subject.get() == "Umum" else ctk.NORMAL)
        if duration_picker is not None:
            duration_picker.set_enabled(not started and selected_mode.get() == "Manual")
        if selected_mode.get() == "Pomodoro":
            balance_frame.pack(fill="x", padx=10, pady=(0, 8), before=button_frame)
        else:
            balance_frame.pack_forget()
        balance = timer_service.break_balance_seconds
        balance_label.configure(text=f"Break balance: {timer_service.format_hms(balance)}")
        available = (not started or choosing or timer_service.can_break_paused_focus()) and not timer_service.is_alarm_active and balance > 0
        break_all_button.configure(
            text=(f"Break {balance // 60} min" if balance % 60 == 0
                  else f"Break {timer_service.format_hms(balance)}"),
            state=ctk.NORMAL if available else ctk.DISABLED,
        )
        choose_duration_button.configure(state=ctk.NORMAL if available else ctk.DISABLED)
        if timer_service.storage_blocked:
            for widget in (primary_button, reset_button, mode_menu, subject_menu, add_subject_button, delete_subject_button,
                           break_all_button, choose_duration_button):
                widget.configure(state=ctk.DISABLED)
            duration_picker.set_enabled(False)
        else:
            refresh_focus_target()
        settings_state = ctk.NORMAL if timer_service.can_change_settings() else ctk.DISABLED
        settings_button.configure(state=settings_state)
        if settings_dialog is not None and settings_dialog.winfo_exists():
            for widget in settings_controls:
                widget.configure(state=settings_state)

    def refresh_focus_target(update_idle_timer=True, idle_remaining=None):
        if selected_mode.get() != "Pomodoro":
            target_progress_label.pack_forget()
            return
        target_progress_label.pack(pady=(0, 12))
        target = config.POMODORO_FOCUS_SECONDS
        if timer_service.is_running:
            progress = timer_service.focus_target_progress()
            progress = 0 if progress is None else progress
        elif update_idle_timer:
            remaining = (timer_service.focus_seconds_remaining(selected_subject.get())
                         if idle_remaining is None else idle_remaining)
            if remaining is None:
                target_progress_label.configure(text="Target progress unavailable")
                countdown_var.set("--:--:--")
                primary_button.configure(text="Retry", state=ctk.NORMAL,
                                         command=lambda: update_control_state(False))
                return
            countdown_var.set(timer_service.format_hms(remaining))
            progress = target - remaining
        else:
            return
        target_progress_label.configure(
            text=f"Target progress: {timer_service.format_hms(progress)} / {timer_service.format_hms(target)}")

    def pomodoro_description():
        scope_text = ("Shared target across subjects." if timer_service.focus_scope == "shared"
                      else "Separate target for each subject.")
        if config.PREVIEW_MODE:
            return ("TEST MODE: Focus 10 sec. Save 5 sec break; 15 sec every 4th focus.\n"
                    f"{scope_text} Test data is separate.")
        return (f"Focus {config.POMODORO_FOCUS_MINUTES} min. Save "
                f"{config.POMODORO_SHORT_BREAK_MINUTES} min break; "
                f"{config.POMODORO_LONG_BREAK_MINUTES} min every {config.POMODORO_TOTAL_SESSIONS}th focus.\n"
                f"{scope_text} After the alarm, continue or take a break.")

    def open_settings():
        nonlocal settings_dialog
        if not timer_service.can_change_settings():
            return
        if settings_dialog is not None and settings_dialog.winfo_exists():
            settings_dialog.focus()
            return
        settings_dialog = dialog = ctk.CTkToplevel(app)
        dialog.title("Settings")
        dialog.geometry("460x550")
        dialog.resizable(False, False)
        dialog.transient(app)
        dialog.grab_set()
        selected_scope = ctk.StringVar(master=dialog, value=timer_service.focus_scope)
        selected_tick = ctk.BooleanVar(master=dialog, value=timer_service.tick_sound_enabled)
        settings_controls.clear()
        ctk.CTkLabel(dialog, text="Pomodoro progress", font=("Helvetica", 18, "bold")).pack(
            anchor="w", padx=20, pady=(18, 12))
        for value, title, explanation in (
            ("shared", "Shared across subjects", "Keep the same remaining target when you change subjects."),
            ("per_subject", "Per subject", "Each subject keeps its own remaining target."),
        ):
            radio = ctk.CTkRadioButton(dialog, text=title, variable=selected_scope, value=value)
            radio.pack(anchor="w", padx=20, pady=(8, 2))
            settings_controls.append(radio)
            ctk.CTkLabel(dialog, text=explanation, wraplength=410, justify="left").pack(
                anchor="w", padx=20, pady=(0, 4))
        ctk.CTkLabel(dialog, text="Both options keep their progress separately.\nSwitching back resumes the progress saved there.",
                     wraplength=410, justify="left").pack(anchor="w", padx=20, pady=(8, 0))
        ctk.CTkLabel(dialog, text="Timer sound", font=("Helvetica", 16, "bold")).pack(
            anchor="w", padx=20, pady=(16, 4))
        tick_switch = ctk.CTkSwitch(dialog, text="Tick every second", variable=selected_tick,
                                    onvalue=True, offvalue=False)
        tick_switch.pack(anchor="w", padx=20, pady=4)
        settings_controls.append(tick_switch)
        volume_label = ctk.CTkLabel(dialog, text=f"Tick volume: {timer_service.tick_volume}%")
        volume_label.pack(anchor="w", padx=20, pady=(8, 0))
        volume_slider = ctk.CTkSlider(
            dialog, from_=0, to=400, number_of_steps=400,
            command=lambda value: volume_label.configure(text=f"Tick volume: {round(value)}%"))
        volume_slider.set(timer_service.tick_volume)
        volume_slider.pack(fill="x", padx=20, pady=(4, 8))
        settings_controls.append(volume_slider)
        ctk.CTkLabel(dialog, text="100% = original volume; above 100% boosts the tick.",
                     wraplength=410, justify="left").pack(anchor="w", padx=20, pady=(0, 4))
        error_label = ctk.CTkLabel(dialog, text="", text_color=("#b00020", "#ff8888"), wraplength=410)
        error_label.pack(fill="x", padx=20, pady=4)

        def cancel():
            nonlocal settings_dialog
            dialog.destroy()
            settings_dialog = None
            settings_controls.clear()

        def save():
            try:
                remaining = timer_service.change_focus_scope(
                    selected_scope.get(), selected_subject.get(), selected_tick.get(), round(volume_slider.get()))
            except (OSError, sqlite3.Error, ValueError) as error:
                error_label.configure(text=f"Could not save Settings: {error}")
                return
            pomodoro_info.configure(text=pomodoro_description())
            refresh_focus_target(idle_remaining=remaining)
            cancel()

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.pack(side="bottom", fill="x", padx=20, pady=(8, 18))
        save_button = ctk.CTkButton(actions, text="Save", command=save)
        save_button.pack(side="right", padx=(8, 0))
        settings_controls.append(save_button)
        ctk.CTkButton(actions, text="Cancel", command=cancel).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Escape>", lambda event: cancel())
        dialog.bind("<Return>", lambda event: save())

    def show_storage_error(message: str) -> None:
        if closing:
            return
        messagebox.showerror("Storage error", message, parent=app)

    def process_ui_events():
        if closing:
            return
        for _ in range(200):
            try:
                kind, value = ui_events.get_nowait()
            except queue.Empty:
                break
            if kind == "countdown":
                if not timer_service.stop_event.is_set():
                    set_countdown(value)
            elif kind == "status":
                set_status(value)
            elif kind == "error":
                show_storage_error(value)
            else:
                update_control_state(timer_service.is_running)
        if not closing:
            app.after(50, process_ui_events)

    timer_service = TimerService(
        lambda value: ui_events.put(("countdown", value)),
        lambda value: ui_events.put(("status", value)),
        lambda *args, **kwargs: ui_events.put(("controls", None)),
        on_storage_error=lambda value: ui_events.put(("error", value)),
    )

    def close_app() -> None:
        nonlocal closing
        if not timer_service.suspend_for_close():
            update_control_state(timer_service.is_running)
            return
        closing = True
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", close_app)

    def set_mode(mode: str) -> None:
        selected_mode.set(mode)
        is_manual = mode == "Manual"
        if duration_picker is not None:
            duration_picker.set_enabled(is_manual and not timer_service.is_running)
        if is_manual:
            duration_label.pack(anchor="w", padx=12, pady=(10, 0), before=pomodoro_info)
            duration_picker.pack(pady=(4, 10), before=pomodoro_info)
            status_var.set("Ready")
            countdown_var.set(
                timer_service.format_hms(
                    config.DEFAULT_HOURS * 3600
                    + config.DEFAULT_MINUTES * 60
                    + config.DEFAULT_SECONDS
                )
            )
        else:
            duration_label.pack_forget()
            duration_picker.pack_forget()
            status_var.set("Pomodoro ready")
            countdown_var.set(timer_service.format_hms(config.POMODORO_FOCUS_SECONDS))
        update_control_state(timer_service.is_running)

    def start_timer() -> None:
        if timer_service.is_running or duration_picker is None:
            return

        if selected_mode.get() == "Pomodoro":
            timer_service.start_pomodoro(selected_subject.get())
            update_control_state(timer_service.is_running)
            return

        total_seconds = duration_picker.get_total_seconds()
        if total_seconds <= 0:
            status_var.set("Duration must be greater than 0")
            return

        countdown_var.set(timer_service.format_hms(total_seconds))
        timer_service.start_timer(total_seconds, selected_subject.get())

    def pause_timer() -> None:
        timer_service.pause_timer()

    def resume_timer() -> None:
        timer_service.resume_timer()

    space_held = False

    def on_space_press(event):
        nonlocal space_held
        if (event.widget.winfo_toplevel() != app
                or event.widget.winfo_class() in ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox")
                or app.grab_current() is not None):
            return
        if space_held:
            return "break"
        space_held = True
        if (not closing and not timer_service.storage_blocked
                and timer_service.is_running and not timer_service.is_alarm_active
                and timer_service.current_phase in ("manual", "focus", "break")):
            if timer_service.pause_event.is_set():
                resume_timer()
            else:
                pause_timer()
        return "break"

    def on_space_release(event):
        nonlocal space_held
        space_held = False

    def on_focus_out(event):
        def clear_if_unfocused():
            if not closing and app.focus_get() is None:
                on_space_release(event)
        app.after_idle(clear_if_unfocused)

    app.bind("<KeyPress-space>", on_space_press, add="+")
    app.bind("<KeyRelease-space>", on_space_release, add="+")
    app.bind("<FocusOut>", on_focus_out, add="+")

    def reset_timer() -> None:
        nonlocal duration_dialog
        if duration_dialog is not None and duration_dialog.winfo_exists():
            duration_dialog.destroy()
        duration_dialog = None
        if not timer_service.reset_timer():
            return
        if history_panel is not None:
            history_panel.refresh()
        errors = []
        while True:
            try:
                event = ui_events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "error":
                errors.append(event)
        for event in errors:
            ui_events.put(event)
        update_control_state(False)
        if duration_picker is not None and selected_mode.get() == "Manual":
            duration_picker.set_hms(
                config.DEFAULT_HOURS,
                config.DEFAULT_MINUTES,
                config.DEFAULT_SECONDS,
            )
            countdown_var.set(
                timer_service.format_hms(
                    config.DEFAULT_HOURS * 3600
                    + config.DEFAULT_MINUTES * 60
                    + config.DEFAULT_SECONDS
                )
            )
        else:
            refresh_focus_target()
            status_var.set("Pomodoro ready")

    def skip_break() -> None:
        timer_service.skip_break()

    def use_break(seconds):
        if not timer_service.start_break(seconds, selected_subject.get()):
            status_var.set("Break unavailable: check balance and timer state")
            return False
        update_control_state(True)
        return True

    def choose_break_duration():
        nonlocal duration_dialog
        if duration_dialog is not None and duration_dialog.winfo_exists():
            duration_dialog.focus()
            return
        duration_dialog = dialog = ctk.CTkToplevel(app)
        dialog.title("Choose break duration")
        dialog.geometry("370x260")
        dialog.resizable(False, False)
        dialog.transient(app)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text=f"Available: {timer_service.format_hms(timer_service.break_balance_seconds)}").pack(pady=(12, 8))
        inputs = ctk.CTkFrame(dialog, fg_color="transparent")
        inputs.pack()
        entries = []
        for index, name in enumerate(("Hours", "Minutes", "Seconds")):
            ctk.CTkLabel(inputs, text=name).grid(row=0, column=index, padx=6)
            entry = ctk.CTkEntry(inputs, width=80, justify="center")
            entry.insert(0, "00")
            entry.grid(row=1, column=index, padx=6)
            entries.append(entry)
        error_label = ctk.CTkLabel(dialog, text="", text_color=("#b00020", "#ff8888"), wraplength=330)
        error_label.pack(pady=8)

        def confirm():
            try:
                values = [entry.get().strip() for entry in entries]
                if any(not value.isascii() or not value.isdigit() for value in values):
                    raise ValueError
                hours, minutes, seconds = map(int, values)
                total = hours * 3600 + minutes * 60 + seconds
                if not (0 <= minutes < 60 and 0 <= seconds < 60 and 0 < total <= timer_service.break_balance_seconds):
                    raise ValueError
            except ValueError:
                error_label.configure(text="Enter a duration above zero and within your balance (minutes/seconds 0-59).")
                return
            if use_break(total):
                dialog.destroy()
            else:
                error_label.configure(text="Break unavailable. Close and try again.")

        ctk.CTkButton(dialog, text="Start Break", command=confirm).pack(pady=4)
        ctk.CTkButton(dialog, text="Cancel", command=dialog.destroy).pack(pady=4)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.bind("<Return>", lambda event: confirm())
        entries[0].focus_set()

    def add_subject():
        if timer_service.is_running or timer_service.storage_blocked:
            return
        dialog = ctk.CTkInputDialog(text="Subject name:", title="Add Subject")
        name = dialog.get_input()
        if name is None:
            return
        try:
            subjects, name = subject_store.add_subject(name)
        except ValueError as error:
            messagebox.showerror("Add Subject", str(error), parent=app)
            return
        except (OSError, UnicodeError) as error:
            show_storage_error(f"Could not save subject: {error}")
            return
        subject_menu.configure(values=subjects)
        selected_subject.set(name)

    def delete_subject(name=None):
        if timer_service.is_running or timer_service.storage_blocked:
            return
        name = selected_subject.get() if name is None else name
        if name == "Umum":
            return
        if not messagebox.askyesno(
            "Delete Subject",
            f'Delete "{name}" from the subject list?\nSession history and focus progress will be kept.',
            parent=app,
        ):
            return
        if timer_service.is_running or timer_service.storage_blocked:
            return
        try:
            subjects = subject_store.delete_subject(name)
        except (OSError, ValueError, UnicodeError) as error:
            show_storage_error(f"Could not delete subject: {error}")
            return
        subject_menu.configure(values=subjects)
        selected_subject.set("Umum")

    def show_subject_context_menu(name, x, y):
        if timer_service.is_running or timer_service.storage_blocked:
            return

        def confirm_delete():
            subject_menu.close_subject_popup()
            delete_subject(name)

        subject_context_menu.delete(0, "end")
        subject_context_menu.add_command(
            label="Hapus", state="disabled" if name == "Umum" else "normal",
            command=confirm_delete,
        )
        subject_context_menu.configure(
            font=subject_menu._apply_font_scaling(subject_menu.cget("dropdown_font")),
            bg=subject_menu._apply_appearance_mode(subject_menu.cget("dropdown_fg_color")),
            fg=subject_menu._apply_appearance_mode(subject_menu.cget("dropdown_text_color")),
            activebackground=subject_menu._apply_appearance_mode(subject_menu.cget("dropdown_hover_color")),
            activeforeground=subject_menu._apply_appearance_mode(subject_menu.cget("dropdown_text_color")),
        )
        subject_menu.post_context_menu(subject_context_menu, x, y)

    main_frame = ctk.CTkFrame(app, corner_radius=0, fg_color="transparent")
    main_frame.pack(fill="both", expand=True, padx=0, pady=0)
    main_frame.grid_columnconfigure(0, weight=3)
    main_frame.grid_columnconfigure(1, weight=0)
    main_frame.grid_rowconfigure(0, weight=1)

    left_frame = ctk.CTkScrollableFrame(main_frame, corner_radius=0, fg_color="transparent")
    left_frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

    right_frame = ctk.CTkFrame(main_frame, corner_radius=12)
    right_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
    right_frame.grid_remove()

    history_visible = False

    def toggle_history():
        nonlocal history_visible
        history_visible = not history_visible
        if history_visible:
            main_frame.grid_columnconfigure(1, weight=2)
            left_frame.grid(padx=(16, 8))
            right_frame.grid()
        else:
            right_frame.grid_remove()
            main_frame.grid_columnconfigure(1, weight=0)
            left_frame.grid(padx=16)
        history_toggle.configure(text="Hide History" if history_visible else "Show History")

    header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
    header_frame.pack(fill="x", padx=10, pady=(8, 12))

    header_label = ctk.CTkLabel(
        header_frame,
        text="⏱️ Timer",
        font=("Helvetica", 22, "bold"),
    )
    header_label.pack(side="left", expand=True)
    history_toggle = ctk.CTkButton(
        header_frame, text="Show History", width=110, command=toggle_history,
    )
    history_toggle.pack(side="right", padx=(8, 0))
    settings_button = ctk.CTkButton(header_frame, text="Settings", width=90, command=open_settings)
    settings_button.pack(side="right", padx=(8, 0))

    subject_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    subject_frame.pack(fill="x", padx=10, pady=(0, 15))

    ctk.CTkLabel(subject_frame, text="Subject", anchor="w").grid(
        row=0, column=0, sticky="w", padx=10, pady=8
    )
    subject_menu = SubjectOptionMenu(
        subject_frame,
        context_command=show_subject_context_menu,
        values=config.SUBJECT_OPTIONS,
        variable=selected_subject,
        width=220,
    )
    subject_menu.grid(row=0, column=1, padx=10, pady=8)
    subject_context_menu = Menu(app, tearoff=False)
    add_subject_button = ctk.CTkButton(subject_frame, text="+", width=32, command=add_subject)
    add_subject_button.grid(row=0, column=2, padx=(0, 10), pady=8)
    delete_subject_button = ctk.CTkButton(subject_frame, text="−", width=32, command=delete_subject)
    delete_subject_button.grid(row=0, column=3, padx=(0, 10), pady=8)
    try:
        subject_menu.configure(values=subject_store.load_subjects())
    except (OSError, ValueError, UnicodeError) as error:
        app.after(0, lambda error=error: show_storage_error(f"Could not load subjects: {error}"))

    mode_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    mode_frame.pack(fill="x", padx=10, pady=(0, 15))

    ctk.CTkLabel(mode_frame, text="Mode", anchor="w").grid(
        row=0, column=0, sticky="w", padx=10, pady=8
    )
    mode_menu = ctk.CTkOptionMenu(
        mode_frame,
        values=["Manual", "Pomodoro"],
        variable=selected_mode,
        command=set_mode,
        width=220,
    )
    mode_menu.grid(row=0, column=1, padx=10, pady=8)

    input_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    input_frame.pack(fill="x", padx=10, pady=(0, 10))

    duration_label = ctk.CTkLabel(input_frame, text="Duration", font=("Helvetica", 13, "bold"))
    duration_label.pack(anchor="w", padx=12, pady=(10, 0))
    duration_picker = DurationPicker(input_frame)
    duration_picker.pack(pady=(4, 10))

    pomodoro_info = ctk.CTkLabel(
        input_frame,
        text=pomodoro_description(),
        font=("Helvetica", 12),
        wraplength=370,
    )
    pomodoro_info.pack(pady=10)

    countdown_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    countdown_frame.pack(fill="x", padx=10, pady=(0, 10))

    countdown_label = ctk.CTkLabel(
        countdown_frame,
        textvariable=countdown_var,
        font=("Consolas", 44, "bold"),
    )
    countdown_label.pack(pady=16)
    target_progress_label = ctk.CTkLabel(countdown_frame, text="", font=("Consolas", 13))

    balance_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    balance_label = ctk.CTkLabel(balance_frame, text="Break balance: 00:00:00", font=("Consolas", 16, "bold"))
    balance_label.pack(pady=(8, 4))
    balance_actions = ctk.CTkFrame(balance_frame, fg_color="transparent")
    balance_actions.pack(fill="x", padx=8, pady=(4, 10))
    break_all_button = ctk.CTkButton(balance_actions, text="Break", command=lambda: use_break(timer_service.break_balance_seconds))
    break_all_button.pack(side="left", fill="x", expand=True, padx=4)
    choose_duration_button = ctk.CTkButton(balance_actions, text="Choose Duration", command=choose_break_duration)
    choose_duration_button.pack(side="left", fill="x", expand=True, padx=4)

    button_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    button_frame.pack(fill="x", padx=10, pady=(0, 8))

    primary_button = ctk.CTkButton(button_frame, text="Start", command=start_timer)
    primary_button.grid(row=0, column=0, padx=8, pady=15, sticky="ew")
    reset_button = ctk.CTkButton(button_frame, text="Reset", command=reset_timer)
    reset_button.grid(row=0, column=1, padx=8, pady=15, sticky="ew")
    skip_break_button = ctk.CTkButton(
        button_frame, text="Skip Break", command=skip_break, state=ctk.DISABLED
    )
    skip_break_button.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 15), sticky="ew")

    button_frame.grid_columnconfigure((0, 1), weight=1)

    status_label = ctk.CTkLabel(left_frame, textvariable=status_var, font=("Helvetica", 14), wraplength=370)
    status_label.pack(pady=(0, 6))

    history_panel = HistoryPanel(right_frame, compact=True)
    history_panel.pack(fill="both", expand=True, padx=8, pady=8)

    selected_subject.trace_add("write", lambda *_: update_control_state(timer_service.is_running))
    set_mode(selected_mode.get())
    restored = timer_service.restore_progress()
    if restored is not None:
        selected_subject.set(restored.subject)
        set_mode(restored.mode)
        if restored.mode == "Manual":
            hours, rest = divmod(restored.total_seconds, 3600)
            minutes, seconds = divmod(rest, 60)
            duration_picker.set_hms(hours, minutes, seconds)
        countdown_var.set(timer_service.format_hms(restored.remaining_seconds))
        status_var.set("Choose: continue focus or use your break balance"
                       if restored.phase == "choice" else "Paused - Resume to continue")
    update_control_state(timer_service.is_running)
    app.after(50, process_ui_events)
    app.mainloop()
