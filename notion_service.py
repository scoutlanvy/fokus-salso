from datetime import datetime
from notion_client import Client

import config

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

notion = Client(auth=config.NOTION_TOKEN)


def get_jakarta_now() -> str:
    jakarta = ZoneInfo(config.TIMEZONE)
    return datetime.now(jakarta).isoformat()


def save_session_to_notion(subject: str, total_seconds: int) -> None:
    duration_minutes = round(total_seconds / 60, 2)
    notion.pages.create(
        parent={"database_id": config.DATABASE_ID},
        properties={
            "Name": {
                "title": [{"text": {"content": f"{subject} Session"}}]
            },
            "Subject": {"select": {"name": subject}},
            "Duration": {"number": duration_minutes},
            "Date": {"date": {"start": get_jakarta_now()}}
        }
    )
