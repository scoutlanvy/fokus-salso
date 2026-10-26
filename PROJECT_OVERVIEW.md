Study Timer
===========

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
external services are not migrated. When the local database cannot be written, the
application shows an error notification but does not stop the timer.

Interface
---------

The application uses a 2-column dashboard layout:

- **Left column**: subject selection, mode (Manual/Pomodoro), duration picker,
  countdown display, a primary button that changes between Start/Pause/Resume,
  a separate Reset button, and Skip Break shown only during Pomodoro breaks,
  and status indicator.
- **Right column**: inline history panel showing summary by subject and list of
  recent sessions. The panel automatically refreshes after a session is successfully saved.

UI uses English language. Theme supports dark and light modes.
Window is resizable (default 900x620).

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
while paused. It returns to Start after reset or completion. Skip Break remains
visible but disabled while a Pomodoro break is paused, and is enabled only when
the current break can be skipped.

When a countdown finishes, the alarm repeats until the primary button, now
labelled Stop Alarm, is pressed. Completed focus sessions are saved before the
alarm starts. Pomodoro waits for the alarm to be stopped before starting its
next focus or break phase. Skip Break is disabled while the alarm is sounding.
Reset cancels both the alarm and the current timer sequence. Closing the window
also stops the alarm.
The bundled `alarm.wav` preserves the 1000 Hz beep pattern. Windows plays it
asynchronously in a loop; Stop Alarm, Reset, and closing the window directly
cancel playback without waiting for the current beep to finish.

History
-------

The inline history panel on the right column has two tabs:

- **Summary**: total duration and session count per subject, sorted by most sessions.
- **Recent Sessions**: list of 30 most recent sessions with time, subject, and duration.

Data is fetched directly from SQLite; the panel shows an empty message if no sessions are saved yet.
The panel auto-refreshes after each completed session is saved.
