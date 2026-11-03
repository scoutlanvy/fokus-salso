"""Application startup: acquire the database mutex before constructing the UI."""

import customtkinter as ctk
from tkinter import messagebox

from focus_timer import config
from focus_timer.instance_lock import InstanceLock, AlreadyRunningError
from focus_timer.ui.main_window import build_main_window


def run_app() -> None:
    try:
        with InstanceLock(config.DATABASE_PATH):
            build_main_window()
    except (AlreadyRunningError, OSError) as error:
        root = ctk.CTk()
        root.iconbitmap(default=str(config.APP_ICON))
        root.withdraw()
        try:
            messagebox.showerror(config.APP_TITLE, str(error), parent=root)
        finally:
            root.destroy()
