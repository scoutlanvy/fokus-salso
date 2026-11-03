import os
from pathlib import Path
import subprocess
import sys


def test_preview_uses_short_durations_and_separate_storage(tmp_path):
    environment = dict(os.environ, STUDY_TIMER_PREVIEW="1", LOCALAPPDATA=str(tmp_path))
    script = r'''
from pathlib import Path
import os
import customtkinter as ctk
from study_timer import config
from study_timer.ui import main_window as gui
from study_timer.app import run_app
from study_timer import session_repository as repository
assert config.PREVIEW_MODE
assert config.POMODORO_FOCUS_SECONDS == 10
assert config.POMODORO_SHORT_BREAK_SECONDS == 5
assert config.POMODORO_LONG_BREAK_SECONDS == 15
assert config.DATA_DIRECTORY == Path(os.environ['LOCALAPPDATA']) / 'StudyTimerPreview'
for expected in [5, 10, 15, 30, 35]:
    assert repository.complete_pomodoro_focus('Umum', config.POMODORO_FOCUS_SECONDS)[0] == expected
assert not (Path(os.environ['LOCALAPPDATA']) / 'StudyTimer').exists()

def inspect(app):
    try:
        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)
        widgets = list(descendants(app))
        assert 'TEST MODE' in app.title()
        mode = next(w for w in widgets if isinstance(w, ctk.CTkOptionMenu) and 'Pomodoro' in w.cget('values'))
        assert mode.get() == 'Pomodoro'
        assert any(isinstance(w, ctk.CTkLabel) and w.cget('textvariable') is not None
                   and str(w.cget('textvariable'))
                   and app.getvar(str(w.cget('textvariable'))) == '00:00:10'
                   for w in widgets)
        assert any(isinstance(w, ctk.CTkLabel) and 'TEST MODE:' in w.cget('text') for w in widgets)
    finally:
        app.destroy()
ctk.CTk.mainloop = inspect
run_app()
'''
    result = subprocess.run([sys.executable, "-c", script], env=environment,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
