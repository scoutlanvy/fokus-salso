from notion_client import Client
from rich.console import Console
from rich.progress import Progress
from rich.panel import Panel
from datetime import datetime
import winsound
import time

# ==========================
# CONFIG
# ==========================
NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
DATABASE_ID = "REDACTED_DATABASE_ID"

SUBJECT = "Anki"
DURATION_MINUTES = 0.5  # 30 detik untuk testing

# ==========================
# INIT
# ==========================
console = Console()
notion = Client(auth=NOTION_TOKEN)

# ==========================
# SAVE TO NOTION
# ==========================
def save_session():
    notion.pages.create(
        parent={"database_id": DATABASE_ID},
        properties={
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": f"{SUBJECT} Session"
                        }
                    }
                ]
            }
        }
    )

# ==========================
# UI
# ==========================
console.print(
    Panel.fit(
        f"[bold cyan]NOTION POMODORO[/bold cyan]\n\n"
        f"Subject : {SUBJECT}\n"
        f"Duration: {DURATION_MINUTES} Minutes",
        title="Study Timer"
    )
)

input("Press ENTER to start...")

# ==========================
# TIMER
# ==========================
total_seconds = int(DURATION_MINUTES * 60)

with Progress() as progress:
    task = progress.add_task(
        "[green]Focus Session...",
        total=total_seconds
    )

    for _ in range(total_seconds):
        time.sleep(1)
        progress.update(task, advance=1)

# ==========================
# FINISHED
# ==========================
console.print("\n[bold green]✅ Session Finished![/bold green]")

for _ in range(3):
    winsound.Beep(1000, 500)

console.print("[yellow]📝 Saving to Notion...[/yellow]")

try:
    save_session()
    console.print("[bold green]✅ Saved to Notion![/bold green]")
except Exception as e:
    console.print(f"[bold red]❌ Error:[/bold red] {e}")

input("\nPress ENTER to exit...")