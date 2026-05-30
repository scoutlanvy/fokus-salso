import customtkinter as ctk
import threading
import time
import winsound
from datetime import datetime
from notion_client import Client

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# ==========================
# CONFIG
# ==========================
NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
DATABASE_ID = "REDACTED_DATABASE_ID"

SUBJECT_OPTIONS = [
    "Anki",
    "English",
    "Linux",
    "Programming",
    "System Admin"
]

DEFAULT_HOURS = 0
DEFAULT_MINUTES = 25
DEFAULT_SECONDS = 0

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("Study Timer")
app.geometry("520x420")
app.resizable(False, False)

# ==========================
# STATE
# ==========================
selected_subject = ctk.StringVar(value=SUBJECT_OPTIONS[0])
hours_var = ctk.StringVar(value=str(DEFAULT_HOURS))
minutes_var = ctk.StringVar(value=str(DEFAULT_MINUTES))
seconds_var = ctk.StringVar(value=str(DEFAULT_SECONDS))
status_var = ctk.StringVar(value="Ready")
countdown_var = ctk.StringVar(value="00:25:00")

timer_thread = None
timer_lock = threading.Lock()
stop_event = threading.Event()
pause_event = threading.Event()
remaining_seconds = 0
is_running = False

notion = Client(auth=NOTION_TOKEN)

# ==========================
# HELPERS
# ==========================
def format_hms(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def get_jakarta_now() -> str:
    jakarta = ZoneInfo("Asia/Jakarta")
    return datetime.now(jakarta).isoformat()


def validate_numeric(value: str, field_name: str) -> int:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} tidak boleh kosong")
    if not stripped.isdigit():
        raise ValueError(f"{field_name} harus angka")
    return int(stripped)


def save_session_to_notion(subject: str, total_seconds: int) -> None:
    duration_minutes = round(total_seconds / 60, 2)
    notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties={
            "Name": {
                "title": [{"text": {"content": f"{subject} Session"}}]
            },
            "Subject": {"select": {"name": subject}},
            "Duration": {"number": duration_minutes},
            "Date": {"date": {"start": get_jakarta_now()}}
        }
    )


def update_control_state(started: bool, paused: bool = False) -> None:
    start_button.configure(state=ctk.DISABLED if started else ctk.NORMAL)
    pause_button.configure(state=ctk.NORMAL if started and not paused else ctk.DISABLED)
    resume_button.configure(state=ctk.NORMAL if paused else ctk.DISABLED)
    reset_button.configure(state=ctk.NORMAL)


def countdown_loop(total_seconds: int) -> None:
    global remaining_seconds, is_running
    remaining_seconds = total_seconds
    stop_event.clear()
    pause_event.clear()
    is_running = True

    update_control_state(started=True)
    status_var.set("Countdown berjalan")

    while remaining_seconds >= 0 and not stop_event.is_set():
        if pause_event.is_set():
            status_var.set("Paused")
            time.sleep(0.2)
            continue

        countdown_var.set(format_hms(remaining_seconds))
        time.sleep(1)
        remaining_seconds -= 1

    if stop_event.is_set():
        return

    if remaining_seconds < 0:
        countdown_var.set("00:00:00")
        status_var.set("Selesai")
        is_running = False
        update_control_state(started=False, paused=False)
        for _ in range(3):
            winsound.Beep(1000, 700)
        save_session_to_notion(selected_subject.get(), total_seconds)
        status_var.set("Selesai dan tersimpan")

# ==========================
# CALLBACKS
# ==========================

def start_timer() -> None:
    global timer_thread
    if is_running:
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

    countdown_var.set(format_hms(total_seconds))
    timer_thread = threading.Thread(target=countdown_loop, args=(total_seconds,), daemon=True)
    timer_thread.start()


def pause_timer() -> None:
    if not is_running or pause_event.is_set():
        return
    pause_event.set()
    status_var.set("Paused")
    update_control_state(started=True, paused=True)


def resume_timer() -> None:
    if not is_running or not pause_event.is_set():
        return
    pause_event.clear()
    status_var.set("Countdown berjalan")
    update_control_state(started=True, paused=False)


def reset_timer() -> None:
    global is_running, remaining_seconds
    stop_event.set()
    pause_event.clear()
    is_running = False
    remaining_seconds = 0
    countdown_var.set(format_hms(DEFAULT_HOURS * 3600 + DEFAULT_MINUTES * 60 + DEFAULT_SECONDS))
    status_var.set("Ready")
    update_control_state(started=False, paused=False)

# ==========================
# LAYOUT
# ==========================
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
    values=SUBJECT_OPTIONS,
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
