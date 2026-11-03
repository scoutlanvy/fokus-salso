# FokusSaldo

**English** | [Bahasa Indonesia](README.id.md)

**Offline study timer with Pomodoro, break balance, and subject tracking.**

A Windows desktop application for tracking study time with a manual timer and Pomodoro sessions. It keeps a persistent break balance, tracks progress by subject, and stores session history locally in SQLite without connecting to external services. The application interface is in English.

Licensed under the [MIT License](LICENSE). Contributions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md) for issue and pull request guidance.

## Features

- Manual timer with hours, minutes, and seconds.
- Pomodoro: 25-minute focus targets with repeating break rewards of 5, 5, 5, and 15 minutes.
- Persistent break balance that you can use when needed.
- Settings for shared or per-subject Pomodoro progress.
- Study subjects, per-subject summaries, and the 30 most recent sessions.
- Pause, Resume, Reset, Skip Break, and an alarm that rings until acknowledged.
- Light and dark theme support.

## Installation

Use Windows with Python 3.9 or newer and Tkinter. Download or clone the repository, then run these commands in PowerShell from the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`tzdata` supplies timezone data for recording sessions in `Asia/Jakarta`.

## Running the application

Double-click `Study Timer.vbs` to open the application without a terminal window. Keep the launcher in the project folder; it uses Python from `.venv`.

To pin the application to the taskbar, create a local shortcut to `.venv\Scripts\pythonw.exe`, pass the full path to `main.py` as its argument, set **Start in** to the project folder, and use `timer.ico` as the icon. Machine-specific `.lnk` files are not included in the repository.

Alternatively, run it from PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py
```

Without saved progress, the application opens in **Pomodoro** mode with a 25-minute focus target waiting for **Start**. Choose a subject if needed. For a manual timer, select **Manual** and set a duration first. After acknowledging a Pomodoro alarm with **Stop Alarm**, choose **Continue Focus** or use your break balance. The next phase waits for your choice.

Press **Space** while the main window is active to **Pause/Resume** a Manual, focus, or break countdown. Space does not start a timer, stop an alarm, or choose the next session. In text inputs, Space remains a normal space. Holding the key changes the state only once.

History starts hidden on every launch. Click **Show History** beside the heading to display summaries and recent sessions, or **Hide History** to give the timer the available width. You can toggle history while running or paused without changing progress. The selected history tab is preserved while the application is open.

To add a subject, click **+** beside **Subject** while the timer is idle, enter a name, and click **OK**. The subject is selected immediately and saved for future launches. Blank names are rejected; case-insensitive duplicates select the existing spelling. Choices are stored in `subjects.json` in the normal or preview data directory, separate from the history database.

To remove a subject from the list, select it, click **?**, and confirm. You can also open the Subject dropdown, right-click a subject, and choose **Hapus** (Delete). Right-clicking does not change the selected subject, and the list stays visible while its context menu is open. Escape returns to the list; clicking outside both popups closes them. Choosing Hapus closes both popups before confirmation. Every subject except **Umum** can be removed; selection then returns to Umum. Session history is kept and remains associated with the same subject name if you add it again. Shared target progress is unchanged. Removal is unavailable while the timer is active or paused, or storage is blocked.

While a Pomodoro focus is **paused**, use **Break** to spend the full balance or **Choose Duration** to select a duration. After the break finishes and its alarm is acknowledged, or after **Skip Break**, the remaining focus returns paused. Click **Resume** when ready. Closing the application during the break preserves both the remaining break and the suspended focus.

## Pomodoro progress settings

Click **Settings** beside **Show History**, choose an option, and click **Save**:

- **Shared across subjects** (default): all subjects continue the same remaining target.
- **Per subject**: each subject keeps its own target. Subjects without progress start at 25 minutes.

Both options retain their progress independently. For example, if the shared target has **18:00** remaining, switching to a previously unused per-subject Anki target shows **25:00**. Switching back to Shared restores **18:00**. Switching does not transfer or duplicate progress. The preference and both sets of progress survive restarts. Legacy per-subject progress remains archived and is not imported into the new Per subject storage, preventing progress previously carried into Shared from being counted again.

Settings can only change while the timer is idle. While running, paused, on a break, sounding an alarm, or waiting for **Continue Focus**, finish or **Reset** the timer first. Resolve storage problems before changing settings. **Cancel**, Escape, or closing the dialog discards unsaved choices. If Save fails, the dialog shows an error and keeps the previous preferences; you can retry Save.

For ticking in every countdown mode, enable **Tick every second**, set **Tick volume** between **0?400%**, and click **Save**. Zero mutes ticking, 100% uses the original volume, and higher values boost it. On/Off and volume preferences survive restarts. This control affects only ticking, leaving the alarm and Windows volume unchanged.

History still records time by subject. Break balance and the reward cycle remain shared under both options. These settings do not change the Manual duration. Preview mode stores its own settings and progress.

## Trying Pomodoro quickly

Double-click `Coba Pomodoro.vbs`. Preview mode uses 10-second focus targets and break rewards of 5, 5, 5, and 15 seconds. Preview data is stored separately. Close its window and open `Study Timer.vbs` to return to normal mode.

## Data storage

- Normal data: `%LOCALAPPDATA%\StudyTimer\study_sessions.sqlite3`
- Preview data: `%LOCALAPPDATA%\StudyTimerPreview\study_sessions.sqlite3`

History, break balance, reward-cycle position, and timer progress survive restarts. To back up the database, close the application and copy the normal database file elsewhere.

## Resuming progress

Manual, Pomodoro focus, and break countdowns save progress every second. If you close the application at `24:52`, it reopens at `24:52` in a paused state. Press **Resume** to continue; time while the application is closed is not counted. The mode and subject are restored and remain locked during the active session.

After a crash or sudden shutdown, recovery uses the last successfully saved second. **Reset** during Pomodoro records elapsed focus time in history and accumulates it toward the 25-minute target in the selected settings scope. For example, after studying for **14:53**, Reset records that segment and displays **10:07** remaining, waiting for **Start**. Completing the remainder reaches the target, awards one break reward, and starts a fresh **25:00** target. History contains **14:53 + 10:07**, without counting the same time twice. Repeated Reset without more study does not reduce the target.

By default, **Shared across subjects** uses one target: switching from Umum to Anki does not change the remaining time. For example, study Umum for **7 minutes**, Reset, and switch to Anki: **18 minutes** remain. Completing those 18 minutes under Anki awards one break reward; history records Umum for 7 minutes and Anki for 18 minutes. The next target returns to 25 minutes.

**Target progress** combines saved accumulation in the selected scope with elapsed time in the current focus. Accumulation survives restarts. Paused time, offline time, and breaks do not count as focus. Reset during a break with a suspended focus records only that focus's elapsed portion. Reset at zero remaining completes the target and awards its reward once. Break balance and the 5, 5, 5, 15-minute reward cycle remain shared across subjects.

On the first upgrade from legacy progress storage to Shared, legacy **Umum** progress becomes the shared target. For example, 6:55 already recorded for Umum leaves **18:05** for every subject. Without Umum progress, the target starts full. If an old focus is still active or suspended during a break, its remaining time and carried target progress are preserved. Migration happens once. Other legacy subjects are kept but not merged. History, break balance, and cycle position are preserved; old history is not recalculated.

Preview mode follows the same rules with a 10-second target and separate storage. If the remaining target cannot be read, **Start** becomes **Retry**; click it to retry the read before starting.

**Reset** in Manual mode discards active progress and returns to **00:00:00**. Existing history, subject choices, and the selected subject are preserved. If a Reset save fails, progress stays paused; fix the storage problem and press **Reset** again.

Closing the application while an alarm sounds does not duplicate the completed session or replay the alarm on restart. Pomodoro shows the next-session choices; Manual returns to idle.

If saving fails, the timer pauses. Press **Resume** to retry. If saving during close fails, the window stays open so you can retry closing. If saved progress cannot be read, timer controls are disabled to protect it; resolve the storage problem, then close and reopen the application.

Only one window is allowed per database. Normal and preview windows can run together because they use different databases.

## Development checks

Install development dependencies and run tests from the project folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Some tests open temporary GUI windows and require a Windows desktop session.

See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for technical details and [AGENTS.md](AGENTS.md) for AI working instructions.

## Code structure

`main.py` remains the entry point for PowerShell, both VBS launchers, and local shortcuts. Keep the launchers in the root alongside `.venv` and `timer.ico`. Include the `focus_timer/` package when copying the project.

- `focus_timer/app.py`: startup and per-database mutex.
- `focus_timer/ui/`: main window, dialogs, subject dropdown, duration input, and history.
- `focus_timer/timer_service.py`: countdown, phase transitions, recovery, and retries.
- `focus_timer/audio.py` and `focus_timer/assets/`: playback and bundled audio.
- `focus_timer/models.py`: timer checkpoint model.
- `focus_timer/session_repository.py`: SQLite queries and transactions.
- `focus_timer/schema.py`: schema setup and migrations within repository transactions.
- `focus_timer/subject_store.py`: JSON subject-list persistence.
- `focus_timer/config.py` and `focus_timer/instance_lock.py`: configuration and Windows mutex.

The code reorganization does not relocate user databases or `subjects.json`. Development imports use the `focus_timer` namespace.
