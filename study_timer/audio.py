"""Windows audio playback and cached tick-volume conversion.

The timer service serializes playback and decides when each sound may start.
"""

import tempfile
import wave
import winsound
from array import array
from pathlib import Path

from study_timer import config


ALARM_SOUND_PATH = config.ASSET_DIRECTORY / "alarm.wav"


class AudioPlayer:
    def __init__(self):
        self.tick_source_path = config.ASSET_DIRECTORY / "tick.wav"
        self._tick_audio_paths = {100: self.tick_source_path}
        self._tick_audio_directory = None

    def prepare_tick(self, volume):
        """Scale PCM once while idle; keep playback timing and the silent tail."""
        if type(volume) is not int or not 0 <= volume <= 400:
            raise ValueError("Tick volume must be between 0 and 400")
        if volume in self._tick_audio_paths:
            return self._tick_audio_paths[volume]
        with wave.open(str(self.tick_source_path), "rb") as sound:
            params = sound.getparams()
            if params.sampwidth != 2 or params.comptype != "NONE":
                raise ValueError("Tick audio must be 16-bit PCM")
            samples = array("h", sound.readframes(sound.getnframes()))
        scaled = array("h", (max(-32768, min(32767, round(sample * volume / 100))) for sample in samples))
        if self._tick_audio_directory is None:
            self._tick_audio_directory = tempfile.TemporaryDirectory(prefix="timer-tick-volume-")
        path = Path(self._tick_audio_directory.name) / f"tick-{volume}.wav"
        with wave.open(str(path), "wb") as sound:
            sound.setparams(params)
            sound.writeframes(scaled.tobytes())
        self._tick_audio_paths[volume] = path
        return path


    def play_alarm(self):
        winsound.PlaySound(
            str(ALARM_SOUND_PATH),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
        )

    def play_tick(self, path):
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def stop(self):
        winsound.PlaySound(None, 0)

    def cleanup(self):
        if self._tick_audio_directory is not None:
            self._tick_audio_directory.cleanup()
            self._tick_audio_directory = None
            self._tick_audio_paths = {100: self.tick_source_path}
