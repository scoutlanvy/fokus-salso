import customtkinter as ctk
import queue
from tkinter import messagebox

import config
from duration_picker import DurationPicker
from history_panel import HistoryPanel
from timer_service import TimerService


def run_app() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.title(config.APP_TITLE)
    app.geometry(config.WINDOW_SIZE)
    app.resizable(config.WINDOW_RESIZABLE, config.WINDOW_RESIZABLE)

    selected_subject = ctk.StringVar(value=config.SUBJECT_OPTIONS[0])
    selected_mode = ctk.StringVar(value="Manual")
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
        if duration_picker is not None:
            duration_picker.set_enabled(not started and selected_mode.get() == "Manual")
        if selected_mode.get() == "Pomodoro":
            balance_frame.pack(fill="x", padx=10, pady=(0, 8), before=button_frame)
        else:
            balance_frame.pack_forget()
        balance = timer_service.break_balance_seconds
        balance_label.configure(text=f"Break balance: {timer_service.format_hms(balance)}")
        available = (not started or choosing) and not timer_service.is_alarm_active and balance > 0
        break_all_button.configure(
            text=(f"Break {balance // 60} min" if balance % 60 == 0
                  else f"Break {timer_service.format_hms(balance)}"),
            state=ctk.NORMAL if available else ctk.DISABLED,
        )
        choose_duration_button.configure(state=ctk.NORMAL if available else ctk.DISABLED)

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
        closing = True
        timer_service.reset_timer()
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
            countdown_var.set(timer_service.format_hms(config.POMODORO_FOCUS_MINUTES * 60))
        update_control_state(timer_service.is_running)

    def start_timer() -> None:
        if timer_service.is_running or duration_picker is None:
            return

        if selected_mode.get() == "Pomodoro":
            countdown_var.set(timer_service.format_hms(config.POMODORO_FOCUS_MINUTES * 60))
            timer_service.start_pomodoro(selected_subject.get())
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

    def reset_timer() -> None:
        nonlocal duration_dialog
        if duration_dialog is not None and duration_dialog.winfo_exists():
            duration_dialog.destroy()
        duration_dialog = None
        timer_service.reset_timer()
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
            countdown_var.set(timer_service.format_hms(config.POMODORO_FOCUS_MINUTES * 60))
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

    update_control_state(started=False)
    app.after(50, process_ui_events)
    app.mainloop()
