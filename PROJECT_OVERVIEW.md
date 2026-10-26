# Study Timer — Technical Overview

Read the sections relevant to the change. Installation, launch instructions,
preview usage, and database paths are documented in [README.md](README.md).

## Main Components

- `main.py`: application entry point.
- `gui.py`: dashboard, timer controls, and Pomodoro decisions.
- `duration_picker.py`: editable Hours/Minutes/Seconds columns.
- `timer_service.py`: countdown, phase transitions, pause/resume, and alarm.
- `session_repository.py`: SQLite persistence and queries.
- `history_panel.py`: subject summaries and recent sessions.
- `config.py`: timezone, storage paths, subjects, durations, and theme values.

## Storage and Failure Handling

Session records contain subject, duration in seconds, and time in `Asia/Jakarta`.
Manual sessions save when countdown completes; Pomodoro sessions save when focus
completes, before the alarm. Records from previous external services are not migrated.

Manual save errors show a notification without stopping the timer. Pomodoro write
failures pause progress: Resume retries the pending transaction; Reset cancels it.
History read failures show an unavailable message without closing the application.

The `pomodoro_state` table holds break balance in seconds and position in the
four-focus reward cycle. Existing databases gain this table with zero balance and
position without changing session history. Saving focus, awarding credit, and
advancing the cycle form one SQLite transaction.

Each running break second is committed before the displayed timer advances. A
forced shutdown can leave at most one uncommitted second. Active timers are not restored.

## Interface and Duration Input

The resizable window defaults to 900x620. The left column contains timer controls
and scrolls in small windows; the right contains history. Subject defaults to `Umum`
in both modes and is recorded like any other subject.

Manual duration starts at `00:00:00` and Reset restores it. Hours accept 0–99;
minutes and seconds accept 0–59, with up to two digits per input. Scrolling down
increases values, scrolling up decreases them, and values wrap at their limits.
Dragging works outside text inputs without changing keyboard focus on hover.

Enter, leaving an input, or Start commits and formats its value to two digits.
Empty or out-of-range input restores the previous committed value. Editing is
disabled while running or paused; duration inputs are hidden in Pomodoro mode.

## Timer Transitions and Alarm

The primary button shows Start, Pause, Resume, Continue Focus, or Stop Alarm
according to state. Reset and completion of an idle break return it to Start.
Skip Break is visible during breaks but disabled while paused or sounding an alarm.

The alarm loops until acknowledged. Pomodoro then waits for an explicit focus or
break decision; no next phase starts automatically. Reset cancels the alarm and
current sequence; closing the window also stops playback.

Windows plays the bundled 1000 Hz `alarm.wav` asynchronously in a loop. Stop Alarm,
Reset, and closing the window cancel playback without waiting for the beep to end.
Worker threads send notifications through a queue consumed by the Tk event loop;
widget updates and error dialogs run on the UI thread.

## Pomodoro Break Bank

Durations are configured in `config.py`; normal focus is 25 minutes with rewards
of 5, 5, 5, then 15 minutes, repeating indefinitely. Balance and cycle position are
shared across subjects and survive Reset and restarts. Interrupted focuses award
nothing; Manual sessions never change the balance.

Break uses the entire balance. Choose Duration accepts a positive duration no
greater than the balance, with minutes and seconds limited to 0–59. Cancel changes
nothing. Break controls are also available when Pomodoro is idle.

Only running break seconds are deducted. Paused time, alarm time, and decision
time cost nothing. Skip Break returns to decision controls; Reset or closing
cancels the active timer and preserves unused credit. A break between focuses
returns to decision controls after acknowledgement; a break started from idle
returns to idle. `POMODORO_ALLOW_SKIP_LONG_BREAK` no longer controls banked breaks.

## History

Summary shows total duration and session count per subject, sorted by most sessions.
Recent Sessions shows the latest 30 sessions with time, subject, and duration.
The panel queries SQLite directly, shows an empty state when needed, and refreshes
after a session saves successfully.

## Preview Isolation

`Coba Pomodoro.vbs` sets `STUDY_TIMER_PREVIEW=1` only for its child process.
Configuration selects separate storage for history, balance, and cycle position,
short durations, and the TEST MODE title. Normal session data remains untouched.
