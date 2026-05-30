import customtkinter as ctk

import config
from timer_service import TimerService


def validate_numeric(value: str, field_name: str) -> int:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} tidak boleh kosong")
    if not stripped.isdigit():
        raise ValueError(f"{field_name} harus angka")
    return int(stripped)


def run_app() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = ctk.CTk()
    app.title(config.APP_TITLE)
    app.geometry(config.WINDOW_SIZE)
    app.resizable(False, False)

    selected_subject = ctk.StringVar(value=config.SUBJECT_OPTIONS[0])
    hours_var = ctk.StringVar(value=str(config.DEFAULT_HOURS))
    minutes_var = ctk.StringVar(value=str(config.DEFAULT_MINUTES))
    seconds_var = ctk.StringVar(value=str(config.DEFAULT_SECONDS))
    status_var = ctk.StringVar(value="Ready")
    countdown_var = ctk.StringVar(value=f"{config.DEFAULT_HOURS:02}:{config.DEFAULT_MINUTES:02}:{config.DEFAULT_SECONDS:02}")

    def set_countdown(value: str) -> None:
        countdown_var.set(value)

    def set_status(value: str) -> None:
        status_var.set(value)

    def update_control_state(started: bool, paused: bool = False) -> None:
        start_button.configure(state=ctk.DISABLED if started else ctk.NORMAL)
        pause_button.configure(state=ctk.NORMAL if started and not paused else ctk.DISABLED)
        resume_button.configure(state=ctk.NORMAL if paused else ctk.DISABLED)
        reset_button.configure(state=ctk.NORMAL)

    timer_service = TimerService(set_countdown, set_status, update_control_state)

    def start_timer() -> None:
        if timer_service.is_running:
            return

        try:
            hours = validate_numeric(hours_var.get(), "Hours")
            minutes = validate_numeric(minutes_var.get(), "Minutes")
            seconds = validate_numeric(seconds_var.get(), "Seconds")
        except ValueError as exc:
            status_var.set(str(exc))
            return

        total_seconds = hours * 3600 + minutes * 60 + seconds
        if total_seconds <= 0:
            status_var.set("Durasi harus lebih dari 0 detik")
            return

        countdown_var.set(timer_service.format_hms(total_seconds))
        timer_service.start_timer(total_seconds, selected_subject.get())

    def pause_timer() -> None:
        timer_service.pause_timer()

    def resume_timer() -> None:
        timer_service.resume_timer()

    def reset_timer() -> None:
        timer_service.reset_timer()
        countdown_var.set(timer_service.format_hms(
            config.DEFAULT_HOURS * 3600 + config.DEFAULT_MINUTES * 60 + config.DEFAULT_SECONDS
        ))

    main_frame = ctk.CTkFrame(app, corner_radius=15)
    main_frame.pack(fill="both", expand=True, padx=20, pady=20)

    header_label = ctk.CTkLabel(
        main_frame,
        text="⏱️ Notion Study Timer",
        font=("Helvetica", 22, "bold")
    )
    header_label.pack(pady=(10, 20))

    subject_frame = ctk.CTkFrame(main_frame, corner_radius=12)
    subject_frame.pack(fill="x", padx=10, pady=(0, 15))

    ctk.CTkLabel(subject_frame, text="Subject", anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=8)
    subject_menu = ctk.CTkOptionMenu(
        subject_frame,
        values=config.SUBJECT_OPTIONS,
        variable=selected_subject,
        width=220
    )
    subject_menu.grid(row=0, column=1, padx=10, pady=8)

    input_frame = ctk.CTkFrame(main_frame, corner_radius=12)
    input_frame.pack(fill="x", padx=10, pady=(0, 15))

    ctk.CTkLabel(input_frame, text="Hours", anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))
    ctk.CTkLabel(input_frame, text="Minutes", anchor="w").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 5))
    ctk.CTkLabel(input_frame, text="Seconds", anchor="w").grid(row=0, column=2, sticky="w", padx=10, pady=(10, 5))

    hours_entry = ctk.CTkEntry(input_frame, textvariable=hours_var, width=100)
    hours_entry.grid(row=1, column=0, padx=10, pady=(0, 10))
    minutes_entry = ctk.CTkEntry(input_frame, textvariable=minutes_var, width=100)
    minutes_entry.grid(row=1, column=1, padx=10, pady=(0, 10))
    seconds_entry = ctk.CTkEntry(input_frame, textvariable=seconds_var, width=100)
    seconds_entry.grid(row=1, column=2, padx=10, pady=(0, 10))

    countdown_frame = ctk.CTkFrame(main_frame, corner_radius=12)
    countdown_frame.pack(fill="both", expand=True, padx=10, pady=(0, 15))

    countdown_label = ctk.CTkLabel(
        countdown_frame,
        textvariable=countdown_var,
        font=("Consolas", 48, "bold")
    )
    countdown_label.pack(expand=True, pady=20)

    button_frame = ctk.CTkFrame(main_frame, corner_radius=12)
    button_frame.pack(fill="x", padx=10, pady=(0, 10))

    start_button = ctk.CTkButton(button_frame, text="Start", command=start_timer)
    start_button.grid(row=0, column=0, padx=8, pady=15, sticky="ew")
    pause_button = ctk.CTkButton(button_frame, text="Pause", command=pause_timer, state=ctk.DISABLED)
    pause_button.grid(row=0, column=1, padx=8, pady=15, sticky="ew")
    resume_button = ctk.CTkButton(button_frame, text="Resume", command=resume_timer, state=ctk.DISABLED)
    resume_button.grid(row=0, column=2, padx=8, pady=15, sticky="ew")
    reset_button = ctk.CTkButton(button_frame, text="Reset", command=reset_timer)
    reset_button.grid(row=0, column=3, padx=8, pady=15, sticky="ew")

    button_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

    status_label = ctk.CTkLabel(main_frame, textvariable=status_var, font=("Helvetica", 14))
    status_label.pack(pady=(0, 10))

    update_control_state(started=False)
    app.mainloop()
