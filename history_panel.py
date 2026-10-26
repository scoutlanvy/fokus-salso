import customtkinter as ctk
from datetime import datetime
from typing import List, Tuple

from session_repository import get_recent_sessions, get_summary_by_subject


def format_duration(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}j {minutes}m"
    return f"{minutes}m"


def format_datetime(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16] if len(iso_str) >= 16 else iso_str


class HistoryPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self,
            text="📊 Riwayat Sesi",
            font=("Helvetica", 18, "bold"),
        )
        header.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))

        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(content_frame)
        self.tabview.grid(row=0, column=0, sticky="nsew")

        self.tab_summary = self.tabview.add("Ringkasan")
        self.tab_recent = self.tabview.add("Sesi Terakhir")

        self.summary_scroll = ctk.CTkScrollableFrame(self.tab_summary)
        self.summary_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self.recent_scroll = ctk.CTkScrollableFrame(self.tab_recent)
        self.recent_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self.refresh()

    def refresh(self) -> None:
        for widget in self.summary_scroll.winfo_children():
            widget.destroy()
        for widget in self.recent_scroll.winfo_children():
            widget.destroy()

        summary = get_summary_by_subject()
        if not summary:
            ctk.CTkLabel(
                self.summary_scroll,
                text="Belum ada data sesi.",
                font=("Helvetica", 13),
                text_color="gray",
            ).pack(pady=20)
        else:
            for subject, total_seconds, count in summary:
                row = ctk.CTkFrame(self.summary_scroll, corner_radius=8)
                row.pack(fill="x", padx=4, pady=3)

                ctk.CTkLabel(
                    row,
                    text=subject,
                    font=("Helvetica", 13, "bold"),
                    anchor="w",
                ).pack(side="left", padx=10, pady=6)

                ctk.CTkLabel(
                    row,
                    text=f"{format_duration(total_seconds)} ({count} sesi)",
                    font=("Helvetica", 12),
                    anchor="e",
                ).pack(side="right", padx=10, pady=6)

        recent = get_recent_sessions(limit=30)
        if not recent:
            ctk.CTkLabel(
                self.recent_scroll,
                text="Belum ada data sesi.",
                font=("Helvetica", 13),
                text_color="gray",
            ).pack(pady=20)
        else:
            for subject, duration_seconds, recorded_at in recent:
                row = ctk.CTkFrame(self.recent_scroll, corner_radius=6)
                row.pack(fill="x", padx=4, pady=2)

                ctk.CTkLabel(
                    row,
                    text=format_datetime(recorded_at),
                    font=("Consolas", 11),
                    text_color="gray",
                    width=90,
                    anchor="w",
                ).pack(side="left", padx=(8, 4), pady=5)

                ctk.CTkLabel(
                    row,
                    text=subject,
                    font=("Helvetica", 12),
                    anchor="w",
                ).pack(side="left", padx=4, pady=5, expand=True, fill="x")

                ctk.CTkLabel(
                    row,
                    text=format_duration(duration_seconds),
                    font=("Helvetica", 12, "bold"),
                    anchor="e",
                ).pack(side="right", padx=10, pady=5)
