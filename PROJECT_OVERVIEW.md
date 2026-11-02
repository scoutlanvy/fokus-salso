# Timer — Technical Overview

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
- `subject_store.py`: default and custom subject choices, atomically saved to `subjects.json` in the selected data directory without changing the session database.
- `instance_lock.py`: Windows named mutex keyed by the resolved database path.

## Storage and Failure Handling

Session records contain subject, duration in seconds, and time in `Asia/Jakarta`.
Manual sessions save when countdown completes; Pomodoro sessions save when focus
completes, before the alarm. Records from previous external services are not migrated.

Timer write failures pause progress: Resume retries the pending transaction; Reset
cancels it after saving elapsed Pomodoro focus. A failed Reset leaves progress
paused and intact; retry Reset to save and clear it.
History read failures show an unavailable message without closing the application.

The `pomodoro_state` table holds break balance in seconds and position in the
four-focus reward cycle. Existing databases gain this table with zero balance and
position without changing session history. Saving focus, awarding credit, and
advancing the cycle form one SQLite transaction.

Each running second is committed before the displayed timer advances. Break debits
and their remaining-time checkpoints share a transaction.

## Progress Recovery

`active_timer` stores one session UUID, mode, subject, phase, original duration,
remaining whole seconds, and whether a break returns to the Pomodoro choice.
Start persists progress before launching a worker. Pause, phase changes, and
normal close also save progress. Offline time and fractional seconds are not counted.

Session completion writes history, any Pomodoro credit, a `timer_completions`
UUID marker, and the next progress state in one transaction. Repeating completion
with the same UUID cannot duplicate history or rewards. Manual completion always
records the original duration, including work before a restart.

After GUI construction, unfinished countdowns restore paused with Resume and
locked mode/subject controls. A completed focus restores to choice without an
alarm; a completed Manual or idle break restores to default idle. A break checkpoint
at zero is similarly treated as completed, even if a crash interrupted its transition.
Reset atomically records elapsed Pomodoro focus and removes active progress, then
joins the old worker before accepting a new session. Elapsed duration is original
minus remaining whole seconds; paused/offline time is excluded. A break with a
suspended focus records only that focus's elapsed duration. Zero elapsed time,
Manual progress, breaks without a suspended focus, and already completed sessions
add no history. The focus UUID completion marker prevents duplicate records on
retry. Partial sessions count toward history summaries and the next focus
target in the selected progress scope. They award no break credit until that target is complete. Reset at
zero remaining finalizes the target and its reward once, including a pending
completion transaction. Manual reset behavior is unchanged.

The singleton `shared_focus_progress` table stores already recorded seconds toward
one target across all subjects, with `migration_version = 1` marking initialization.
On first access, migration copies the actual legacy `Umum` accumulation, or zero
if absent. If a legacy active or suspended focus exists, its carried portion
(`POMODORO_FOCUS_SECONDS - total_seconds`) takes precedence so its remaining time
is preserved; a completed choice starts a fresh target. Migration and initialization
share the transaction and are retried on failure. Legacy `subject_focus_progress`
rows, history, break balance, and cycle position remain untouched. Old subject
rows are no longer read after migration, and history is not reinterpreted.

Reset adds only the new segment's elapsed seconds to the selected scope in the same
transaction as subject-specific history, UUID marker, and checkpoint removal.
The next segment lasts `POMODORO_FOCUS_SECONDS - accumulated_seconds`; its
`active_timer.total_seconds` stores this shortened duration. Completion saves only
the final segment under its subject, clears that target's accumulation, awards the break
reward, advances the cycle, and checkpoints choice atomically. Earlier segments
never count twice. Repository `get_focus_progress(subject="Umum")` and service
`focus_seconds_remaining(subject="Umum")` read the target using the persisted scope.
Normal and preview data remain isolated.

`pomodoro_settings` stores `focus_scope` (`shared` by default or `per_subject`)
and `tick_sound` (off by default), plus `tick_volume_percent` (0–400, default 100).
The legacy `tick_volume` column keeps its 0–100 constraint. On migration, its saved
value initializes `tick_volume_percent`. New saves write the actual percentage to
the new column and cap the legacy value at 100, avoiding a table rebuild.
Older tables gain missing columns without changing saved preferences or history.
`get_tick_sound()` / `set_tick_sound()` read and save On/Off; `get_tick_volume()`
reads volume. Settings Save passes optional tick preferences to `set_focus_scope()`
so scope, On/Off, volume, and destination progress validation share one transaction.
The new `per_subject_focus_progress` table starts empty; it never imports archived
`subject_focus_progress` rows, which may already have contributed to shared progress.
Changing scope does not copy, clear, or merge progress. Each scope resumes its own
saved target. Break balance and reward-cycle position stay shared.
`get_focus_scope()` reads the preference; `set_focus_scope(scope, subject)` saves it
and validates/returns destination progress in one transaction. It rejects unfinished
checkpoints; finished `done` checkpoints are safe. Save or destination-read failure
rolls back the preference. The service also serializes changes under its command
lock and rejects running timers, live workers, alarms, retries, or blocked storage.
The preference therefore stays fixed for active and suspended focus checkpoints,
including recovery after restart, without changing their existing schema.

Close freezes progress under the command lock, saves it, then stops and joins the
worker. A write failure keeps the window open; countdowns stay paused. A recovery
read failure blocks timer controls to prevent overwriting unread progress.
The Windows mutex is acquired before database initialization and released on exit
or process death. Normal and preview paths use different mutexes and databases.

## Interface and Duration Input

The window title and main heading use Timer; preview windows use Timer - TEST MODE.
`timer.ico` supplies multiple icon sizes for Windows. `config.APP_ICON` resolves
it beside the code, and main/error windows set it explicitly before displaying.
The local and pinned Timer shortcuts also reference this file for their icons.

Without saved progress, launch defaults to Pomodoro. Mode initialization displays
the configured focus duration and controls without starting the timer. Recovery
then applies the saved mode and remaining time. Idle Pomodoro displays the
selected scope's remaining target and waits for Start. Manual remains selectable when idle.
The Target progress label combines recorded accumulation with the active segment's
elapsed seconds, including a suspended focus during its break. The info text identifies
the target as shared or separate per subject. Changing subject preserves the shared
target or loads that subject's own target. Subject changes, Reset, and mode changes
refresh the target. Failed idle progress reads replace
Start with Retry until a successful read; starting also rechecks storage before
creating a checkpoint. Active preparation failures pause for Resume to retry.

Settings beside Show History opens a modal dialog with Shared across subjects and
Per subject radio choices, a Tick every second switch, a 0–400% tick volume slider,
explanatory text, Save, and Cancel. The dialog uses the
saved preference; Cancel/Escape/window-close discard only its pending selection.
Save refreshes the info text and, in Pomodoro, countdown and Target progress from
the transaction's returned value, avoiding a second read after commit. Failure
keeps the dialog open with an error and preserves the main display/preference.
Settings is disabled during all active phases (including pause, alarm and choice),
storage blocks, and idle target-read failures. A successful Retry re-enables it.
Manual duration is unaffected by changing the Pomodoro progress preference. The
tick sound applies to every countdown phase (Manual, Pomodoro focus, and breaks),
starts when the countdown starts or resumes, and stays saved across restarts.
`tick.wav` contains a 35 ms tick at the start with silence up to one second. Keep
this trailing silence: shortening the file caused delayed/intermittent tick
playback reported on Windows. The silence does not delay the sound's onset. It plays
once on Start/Resume and once alongside each nonzero countdown update after its
checkpoint succeeds. Playback has no independent loop, so storage delays cannot
cause additional ticks while the displayed second is unchanged. Pause, storage
errors, Reset, close, and countdown exit stop playback before the completion alarm.
The completion alarm remains independent of this switch.
Volume scales only the tick's 16-bit PCM samples; 0% mutes ticking, 100% preserves
the original audio, and 101–400% boosts it. The bundled audio has sufficient
headroom for 400%; scaling also clamps samples to the signed 16-bit range. The service
prepares and caches scaled one-second WAV files in a system temporary directory
while idle, before committing Settings, so countdown playback performs no audio
conversion. Source audio, onset, duration, and silent tail stay intact. Normal
close cleans these generated files; failed saves preserve all active preferences.
Alarm and Windows system volume are unaffected.

The resizable window defaults to 900x620. The left column contains timer controls
and scrolls in small windows; the right contains history. History starts hidden on
every launch. Show History / Hide History beside the title toggles the existing
panel with grid removal, preserving its selected tab and refresh behavior. While
hidden, its column has zero weight and the timer fills the available width;
showing it restores the 3:2 column weights. Visibility is not persisted and the
toggle remains available during running and paused timers. Padding changes use
`CTkScrollableFrame.grid()` to update its outer wrapper; inherited `grid_configure()`
would instead re-layout the inner content and break its canvas-width tracking.
The timer content and cards follow the canvas width through toggles and resizes.
Subject defaults to `Umum`
in both modes and is recorded like any other subject.
The adjacent + button opens an Add Subject input dialog while idle. Successful
save selects the subject immediately; blank names are rejected and case-insensitive
duplicates select the existing spelling. Storage failures leave the selection
unchanged and show an error. Normal and preview subject lists are isolated.
The adjacent − button confirms removal of the selected choice, except `Umum`,
then selects `Umum` and refreshes its target. It is disabled while active or paused
and when storage is blocked. History and focus progress remain untouched.
Right-clicking a dropdown item opens a `Hapus` context menu without selecting it.
The subject list stays visible while the context menu owns focus/mouse capture.
Escape or cancellation returns focus/capture to the list; a click outside both
popups closes both. Selecting Hapus closes both before asking for confirmation.
Focus-loss dismissal is suspended during the context menu. A temporary Windows
MSGF_MENU hook on the GUI thread distinguishes native outside-click dismissal
from Escape; the hook is always removed after the native menu returns.
`Umum` has a disabled action. The menu shares the − button's confirmation and
deletion flow, including rechecking timer/storage state after confirmation.
SubjectOptionMenu retains the CTkOptionMenu control but displays subject rows in a
scrollable Tk Toplevel popup, since native Windows menus do not reliably deliver
per-item right-click events. Rows bind their subject names directly. Escape,
outside clicks, and focus loss close the popup; the mode dropdown is unchanged.
Left-click opening is deferred until idle so CTk's global click-focus binding
finishes before focus moves into the popup, preventing immediate dismissal.
Popup height uses widget scaling to match the row heights on high-DPI Windows
displays. The context menu uses the dropdown font/colors and Tk's popup lifecycle
so mouse selection and dismissal work with the appropriate menu grab.
`subjects.json` version 1 stores the complete list as `{"version": 1, "subjects": [...]}`.
Legacy arrays still merge with defaults; the next successful list change writes
version 1 atomically so deleted defaults stay removed after restart.

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

Space pauses/resumes active Manual, focus, and break countdowns while the main
window has focus. It ignores text inputs and modal dialogs, and never starts a
timer, acknowledges alarms, or continues a choice. Repeated key presses while
held are suppressed until release; losing window focus clears the held state.

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
shared across subjects and survive Reset and restarts. Focus accumulation follows
the Settings choice; completed targets in either scope award the next shared reward. History records
each segment under the subject used for that segment. Manual sessions never change the balance or focus accumulation.

Break uses the entire balance. Choose Duration accepts a positive duration no
greater than the balance, with minutes and seconds limited to 0–59. Cancel changes
nothing. Break controls are also available when Pomodoro is idle.
They are also available while a Pomodoro focus is paused. The additive nullable
`active_timer.suspended_focus` JSON column preserves the focus UUID, duration,
subject, and remaining seconds during its break. After the break alarm is
acknowledged or the break is skipped, that same focus returns paused. Recovery
preserves both countdowns; a zero-second break restores its suspended focus
directly. Manual timers and paused breaks cannot start another break.

Only running break seconds are deducted. Paused time, alarm time, and decision
time cost nothing. Skip Break returns to decision controls; Reset cancels the
active timer, while closing preserves it for recovery. Both preserve unused credit.
A break between focuses
returns to decision controls after acknowledgement; a break started from idle
returns to idle. `POMODORO_ALLOW_SKIP_LONG_BREAK` no longer controls banked breaks.

## History

Summary shows total duration and session count per subject, sorted by most sessions.
Recent Sessions shows the latest 30 sessions with time, subject, and duration.
The panel queries SQLite directly, shows an empty state when needed, and refreshes
after a session saves successfully.
Successful Reset also refreshes history immediately, keeping the selected subject.

## Preview Isolation

`Coba Pomodoro.vbs` sets `STUDY_TIMER_PREVIEW=1` only for its child process.
Configuration selects separate storage for history, balance, and cycle position,
short durations, and the TEST MODE title. Normal session data remains untouched.
