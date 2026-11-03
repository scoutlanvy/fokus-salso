"""Exercise the stable entry point with isolated storage and an unrelated cwd."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("preview", [False, True])
def test_main_entrypoint_resolves_assets_and_isolates_storage(tmp_path, preview):
    project = Path(__file__).resolve().parents[1]
    script = r'''
import os
from pathlib import Path
import runpy
import sys

project = Path(sys.argv[1])
sys.path.insert(0, str(project))
import customtkinter as ctk
from focus_timer import config
from focus_timer import session_repository as repository

expected_directory = Path(os.environ['LOCALAPPDATA']) / (
    'StudyTimerPreview' if config.PREVIEW_MODE else 'StudyTimer')
assert config.DATA_DIRECTORY == expected_directory
assert config.APP_ICON.is_file()
assert (config.ASSET_DIRECTORY / 'alarm.wav').is_file()
assert (config.ASSET_DIRECTORY / 'tick.wav').is_file()

def inspect(app):
    try:
        app.update_idletasks()
        assert app.title() == config.APP_TITLE
        assert repository.get_recent_sessions() == []
        assert config.DATABASE_PATH.is_file()
        other = 'StudyTimer' if config.PREVIEW_MODE else 'StudyTimerPreview'
        assert not (expected_directory.parent / other).exists()
    finally:
        app.tk.call(app.protocol('WM_DELETE_WINDOW'))

ctk.CTk.mainloop = inspect
runpy.run_path(str(project / 'main.py'), run_name='__main__')
'''
    environment = dict(
        os.environ,
        LOCALAPPDATA=str(tmp_path),
        STUDY_TIMER_PREVIEW="1" if preview else "0",
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(project)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
