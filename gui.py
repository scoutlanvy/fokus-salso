import customtkinter as ctk
import queue
from tkinter import messagebox

import config
from duration_picker import DurationPicker
from history_panel import HistoryPanel
from timer_service import TimerService
from instance_lock import InstanceLock, AlreadyRunningError
import subject_store


def run_app() -> None:
    try:
        with InstanceLock(config.DATABASE_PATH):
            _run_app()
    except (AlreadyRunningError, OSError) as error:
        root = ctk.CTk()
        root.withdraw()
        try:
            messagebox.showerror("Study Timer", str(error), parent=root)
        finally:
            root.destroy()


def _run_app() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
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
            for widget in (primary_button, reset_button, mode_menu, subject_menu, add_subject_button,
                           break_all_button, choose_duration_button):
                widget.configure(state=ctk.DISABLED)
            duration_picker.set_enabled(False)
        else:
            refresh_focus_target()

    def refresh_focus_target(update_idle_timer=True):
        if selected_mode.get() != "Pomodoro":
            target_progress_label.pack_forget()
            return
        target_progress_label.pack(pady=(0, 12))
        target = config.POMODORO_FOCUS_SECONDS
        if timer_service.is_running:
            progress = timer_service.focus_target_progress()
            progress = 0 if progress is None else progress
        elif update_idle_timer:
            remaining = timer_service.focus_seconds_remaining(selected_subject.get())
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

    main_frame = ctk.CTkFrame(app, corner_radius=0, fg_color="transparent")
    main_frame.pack(fill="both", expand=True, padx=0, pady=0)
    main_frame.grid_columnconfigure(0, weight=3)
    main_frame.grid_columnconfigure(1, weight=2)
    main_frame.grid_rowconfigure(0, weight=1)

    left_frame = ctk.CTkScrollableFrame(main_frame, corner_radius=0, fg_color="transparent")
    left_frame.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)

    right_frame = ctk.CTkFrame(main_frame, corner_radius=12)
    right_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)

    header_label = ctk.CTkLabel(
        left_frame,
        text="⏱️ Study Timer",
        font=("Helvetica", 22, "bold"),
    )
    header_label.pack(pady=(8, 12))

    subject_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    subject_frame.pack(fill="x", padx=10, pady=(0, 15))

    ctk.CTkLabel(subject_frame, text="Subject", anchor="w").grid(
        row=0, column=0, sticky="w", padx=10, pady=8
    )
    subject_menu = ctk.CTkOptionMenu(
        subject_frame,
        values=config.SUBJECT_OPTIONS,
        variable=selected_subject,
        width=220,
    )
    subject_menu.grid(row=0, column=1, padx=10, pady=8)
    add_subject_button = ctk.CTkButton(subject_frame, text="+", width=32, command=add_subject)
    add_subject_button.grid(row=0, column=2, padx=(0, 10), pady=8)
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
        text=(
            "TEST MODE: Focus 10 sec. Save 5 sec break; 15 sec every 4th focus.\n"
            "Test balance and history are separate."
            if config.PREVIEW_MODE else
            f"Focus {config.POMODORO_FOCUS_MINUTES} min. Save "
            f"{config.POMODORO_SHORT_BREAK_MINUTES} min break; "
            f"{config.POMODORO_LONG_BREAK_MINUTES} min every {config.POMODORO_TOTAL_SESSIONS}th focus.\n"
            "After the alarm, choose to continue or take a break."
        ),
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
