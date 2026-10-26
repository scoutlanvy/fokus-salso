Study Timer
===========

Quick Launch (Windows)
----------------------

Double-click `Study Timer.vbs` to open the application without a terminal.
The launcher uses `.venv\Scripts\pythonw.exe` from the project folder.
For desktop access, create a shortcut to `Study Timer.vbs` using Windows
Send to > Desktop (create shortcut). Keep the launcher inside the project folder.

Desktop application using CustomTkinter to track study sessions through manual
or Pomodoro timers. Completed focus sessions are saved locally to SQLite,
without connection to external services.

Main Components
---------------

- `main.py`: application entry point.
- `gui.py`: 2-column dashboard interface with subject selection, mode selection,
  timer controls on the left column, and inline history panel on the right.
- `timer_service.py`: manual and Pomodoro countdown, including pause, resume,
  reset, skip break, and a repeating alarm that waits for acknowledgement.
- `session_repository.py`: storage and query of sessions from SQLite.
- `history_panel.py`: inline history panel with summary by subject and recent sessions tabs.
- `config.py`: timezone, local database location, subject options, and duration settings.

Storage
-------

Database is created automatically at `%LOCALAPPDATA%\StudyTimer\study_sessions.sqlite3`
on Windows. Records contain subject, duration in seconds, and session time in
`Asia/Jakarta` timezone. Manual sessions are saved when countdown completes; each
Pomodoro focus session is saved when the focus phase completes. Records from previous
external services are not migrated. Manual save errors show a notification without
stopping the timer. Pomodoro write failures pause progress; Resume retries the
pending transaction and Reset cancels it. History read failures show an unavailable
message without closing the application.

The `pomodoro_state` table stores a single break balance in seconds and the
completed-focus position in the four-focus cycle. Existing databases get this
table automatically with zero balance and position, without altering session
history. Saving a completed Pomodoro focus, awarding its break credit, and
advancing the cycle are one SQLite transaction. Each elapsed break second is
committed before advancing the displayed timer. A forced shutdown can leave at
most one uncommitted second; active timers are not restored.

Interface
---------

The application uses a 2-column dashboard layout:

- **Left column**: subject selection, mode (Manual/Pomodoro), duration picker,
  countdown display, a primary button that changes between Start/Pause/Resume,
  a separate Reset button, Skip Break during Pomodoro breaks, break balance and
  spending controls in Pomodoro mode, and a status indicator. The left column
  scrolls in smaller windows; duration inputs are hidden in Pomodoro mode.
- **Right column**: inline history panel showing summary by subject and list of
  recent sessions. The panel automatically refreshes after a session is successfully saved.

UI uses English language. Theme supports dark and light modes.
The default subject is `Umum` in both Manual and Pomodoro modes, so a session
can start without choosing a specific category. Other subjects remain selectable.
Sessions under `Umum` are saved and displayed in history like any other subject;
existing history is unchanged.
Window is resizable (default 900x620).

Manual duration starts at `00:00:00` and returns to that value on Reset.
In Manual mode, duration can be set by scrolling or typing the center value in
each Hours/Minutes/Seconds column. Scrolling down increases the value; scrolling
up decreases it, wrapping at the limits. Dragging remains available outside the
text inputs without moving keyboard focus on hover. Hours accept 0-99, minutes
and seconds accept 0-59, with up to two digits per input. Enter, leaving the input,
or pressing Start commits the value and formats it with two digits. Empty or
out-of-range input reverts to the previous committed value. Duration editing is
disabled while running or paused and in Pomodoro mode; Pomodoro durations remain
configured in `config.py`.

The primary timer button shows Start when idle, Pause while running, and Resume
while paused. At a Pomodoro decision it shows Continue Focus. It returns to Start
after reset or an idle break completes. Skip Break remains visible but disabled
while a break is paused or its alarm is sounding. Every banked break can be skipped.

When a countdown finishes, the alarm repeats until the primary button, now
labelled Stop Alarm, is pressed. Completed focus sessions are saved before the
alarm starts. Pomodoro waits for Stop Alarm, then waits for an explicit decision
to continue focus or use break balance. No next phase starts automatically.
Reset cancels both the alarm and the current timer sequence. Closing the window
also stops the alarm.
The bundled `alarm.wav` preserves the 1000 Hz beep pattern. Windows plays it
asynchronously in a loop; Stop Alarm, Reset, and closing the window directly
cancel playback without waiting for the current beep to finish.

Pomodoro Break Bank
-------------------

Focus lasts 25 minutes. Completed focuses award 5, 5, 5, then 15 minutes of break
credit, repeating without a four-session limit. The cycle position and balance
are shared across subjects and survive Reset and application restarts. Interrupted
focuses award nothing; Manual sessions never change the balance.

After Stop Alarm, Continue Focus starts another focus. The Break button uses
the entire balance; Choose Duration accepts hours/minutes/seconds above zero
and no greater than the balance (minutes and seconds must be 0-59). Cancel
changes nothing. These break controls are also available when Pomodoro is idle.

Only running break seconds are deducted, not paused time, alarm time, or decision
time. Skip Break returns to the decision controls; Reset or closing the app
cancels the active timer. All unused credit remains saved. A break taken between
focuses returns to the decision controls after its alarm; a completed break
started from idle returns to idle after its alarm is acknowledged. The previous
`POMODORO_ALLOW_SKIP_LONG_BREAK` setting no longer controls banked breaks.

Worker threads send notifications through a queue consumed by the Tk event loop;
widget changes and error dialogs run only on the UI thread.

History
-------

The inline history panel on the right column has two tabs:

- **Summary**: total duration and session count per subject, sorted by most sessions.
- **Recent Sessions**: list of 30 most recent sessions with time, subject, and duration.

Data is fetched directly from SQLite; the panel shows an empty message if no sessions are saved yet.
The panel auto-refreshes after each completed session is saved.
