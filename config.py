try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
DATABASE_ID = "REDACTED_DATABASE_ID"
TIMEZONE = "Asia/Jakarta"

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

MAX_HOURS = 99
MAX_MINUTES = 59
MAX_SECONDS = 59

APP_TITLE = "Study Timer"
WINDOW_SIZE = "520x560"
