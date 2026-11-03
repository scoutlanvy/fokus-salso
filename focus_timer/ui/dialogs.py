"""Settings and break-duration dialogs; commands are supplied by the main window."""

import sqlite3

import customtkinter as ctk


def create_settings_dialog(app, timer_service, selected_subject, on_saved, on_cancel, settings_controls):
    dialog = ctk.CTkToplevel(app)
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
        dialog.destroy()
        settings_controls.clear()
        on_cancel()

    def save():
        try:
            remaining = timer_service.change_focus_scope(
                selected_scope.get(), selected_subject.get(), selected_tick.get(), round(volume_slider.get()))
        except (OSError, sqlite3.Error, ValueError) as error:
            error_label.configure(text=f"Could not save Settings: {error}")
            return
        on_saved(remaining)
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

    return dialog


def create_break_duration_dialog(app, timer_service, use_break):
    dialog = ctk.CTkToplevel(app)
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

    return dialog
