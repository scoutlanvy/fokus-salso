import os
from pathlib import Path

TIMEZONE = "Asia/Jakarta"
DATA_DIRECTORY = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "StudyTimer"
DATABASE_PATH = DATA_DIRECTORY / "study_sessions.sqlite3"

SUBJECT_OPTIONS = [
    "Umum",
    "Anki",
    "English",
    "Linux",
    "Programming",
    "System Admin"
]

DEFAULT_HOURS = 0
DEFAULT_MINUTES = 0
DEFAULT_SECONDS = 0

POMODORO_FOCUS_MINUTES = 25
POMODORO_SHORT_BREAK_MINUTES = 5
POMODORO_LONG_BREAK_MINUTES = 15
POMODORO_TOTAL_SESSIONS = 4
POMODORO_ALLOW_SKIP_LONG_BREAK = False

MAX_HOURS = 99
MAX_MINUTES = 59
MAX_SECONDS = 59

APP_TITLE = "Study Timer"
WINDOW_SIZE = "900x620"
WINDOW_RESIZABLE = True

COLOR_BG_MAIN = ("#f5f5f5", "#0d1220")
COLOR_BG_CARD = ("#ffffff", "#171e2d")
COLOR_ACCENT = ("#4263eb", "#5579f7")
COLOR_TEXT_PRIMARY = ("#1a1a1a", "#edf1f8")
COLOR_TEXT_SECONDARY = ("#666666", "#8994a6")
COLOR_BORDER = ("#e0e0e0", "#2b3547")
