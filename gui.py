import customtkinter as ctk
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

    def set_countdown(value: str) -> None:
        countdown_var.set(value)

    def set_status(value: str) -> None:
        status_var.set(value)
        if history_panel is not None and ("saved" in value.lower() or "completed" in value.lower()):
            app.after(100, history_panel.refresh)

    def update_control_state(
        started: bool,
        paused: bool = False,
        can_skip_break: bool = False,
    ) -> None:
        if not started:
            primary_button.configure(text="Start", command=start_timer)
        elif paused:
            primary_button.configure(text="Resume", command=resume_timer)
        else:
            primary_button.configure(text="Pause", command=pause_timer)
        reset_button.configure(state=ctk.NORMAL)
        skip_break_button.configure(state=ctk.NORMAL if can_skip_break else ctk.DISABLED)
        if started and timer_service.current_phase in ("short_break", "long_break"):
            skip_break_button.grid()
        else:
            skip_break_button.grid_remove()
        mode_menu.configure(state=ctk.DISABLED if started else ctk.NORMAL)
        subject_menu.configure(state=ctk.DISABLED if started else ctk.NORMAL)
        if duration_picker is not None:
            duration_picker.set_enabled(not started and selected_mode.get() == "Manual")

    def show_storage_error(message: str) -> None:
        app.after(
            0,
            lambda: messagebox.showerror("Save failed", message, parent=app),
        )

    timer_service = TimerService(
        set_countdown,
        set_status,
        update_control_state,
        on_storage_error=show_storage_error,
    )

    def set_mode(mode: str) -> None:
        selected_mode.set(mode)
        is_manual = mode == "Manual"
        if duration_picker is not None:
            duration_picker.set_enabled(is_manual and not timer_service.is_running)
        if is_manual:
            status_var.set("Ready")
            countdown_var.set(
                timer_service.format_hms(
                    config.DEFAULT_HOURS * 3600
                    + config.DEFAULT_MINUTES * 60
                    + config.DEFAULT_SECONDS
                )
            )
        else:
            status_var.set("Pomodoro ready")
            countdown_var.set(timer_service.format_hms(config.POMODORO_FOCUS_MINUTES * 60))

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

    main_frame = ctk.CTkFrame(app, corner_radius=0, fg_color="transparent")
    main_frame.pack(fill="both", expand=True, padx=0, pady=0)
    main_frame.grid_columnconfigure(0, weight=3)
    main_frame.grid_columnconfigure(1, weight=2)
    main_frame.grid_rowconfigure(0, weight=1)

    left_frame = ctk.CTkFrame(main_frame, corner_radius=0, fg_color="transparent")
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

    ctk.CTkLabel(input_frame, text="Duration", font=("Helvetica", 13, "bold")).pack(
        anchor="w", padx=12, pady=(10, 0)
    )
    duration_picker = DurationPicker(input_frame)
    duration_picker.pack(pady=(4, 10))

    pomodoro_info = ctk.CTkLabel(
        input_frame,
        text=(
            f"Pomodoro: {config.POMODORO_TOTAL_SESSIONS} sessions focus "
            f"{config.POMODORO_FOCUS_MINUTES} min, break "
            f"{config.POMODORO_SHORT_BREAK_MINUTES}/{config.POMODORO_LONG_BREAK_MINUTES} min"
        ),
        font=("Helvetica", 12),
    )
    pomodoro_info.pack(pady=(0, 10))

    countdown_frame = ctk.CTkFrame(left_frame, corner_radius=12)
    countdown_frame.pack(fill="x", padx=10, pady=(0, 10))

    countdown_label = ctk.CTkLabel(
        countdown_frame,
        textvariable=countdown_var,
        font=("Consolas", 44, "bold"),
    )
    countdown_label.pack(pady=16)

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

    status_label = ctk.CTkLabel(left_frame, textvariable=status_var, font=("Helvetica", 14))
    status_label.pack(pady=(0, 6))

    history_panel = HistoryPanel(right_frame, compact=True)
    history_panel.pack(fill="both", expand=True, padx=8, pady=8)

    update_control_state(started=False)
    app.mainloop()
