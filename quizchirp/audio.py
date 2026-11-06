from array import array
import math
import random
import sys
import threading
import wave
from pathlib import Path
from .config import Settings
from .answers import CHOICES

import sounddevice as sd

SOUNDS = Path(__file__).with_name("sounds")
VOICES = tuple(sorted(path.stem for path in SOUNDS.glob("finch-*.wav")))
GAIN_DB_RANGE = (-3.0, 2.0)
PITCH_SEMITONE_RANGE = (-0.8, 0.8)
PEAK_LIMIT = 30000


def _vary_note(data):
    """Apply one subtle variation to a little-endian mono PCM16 answer note."""
    gain = 10 ** (random.triangular(*GAIN_DB_RANGE, 0.0) / 20)
    speed = 2 ** (random.triangular(*PITCH_SEMITONE_RANGE, 0.0) / 12)
    samples = array("h", data)
    if sys.byteorder != "little":
        samples.byteswap()
    if speed == 1.0:
        shifted = samples
    else:
        # Windowed-sinc resampling preserves the recording's high frequencies.
        # Filter before shortening the note to avoid aliasing; keep the device rate.
        radius = 16
        cutoff = min(1.0, 1.0 / speed)
        shifted = []
        for frame in range(round(len(samples) / speed)):
            position = frame * speed
            center = math.floor(position)
            value = weight_sum = 0.0
            for index in range(center - radius + 1, center + radius + 1):
                distance = position - index
                phase = math.pi * distance * cutoff
                sinc = math.sin(phase) / phase if phase else 1.0
                weight = cutoff * sinc * (0.5 + 0.5 * math.cos(math.pi * distance / radius))
                weight_sum += weight
                if 0 <= index < len(samples):
                    value += samples[index] * weight
            shifted.append(value / weight_sum)
    peak = max((abs(value) for value in shifted), default=0)
    if peak:
        # Reserve headroom using a uniform gain reduction, without hard clipping.
        gain = min(gain, PEAK_LIMIT / peak)
    result = array("h", (round(value * gain) for value in shifted))
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


class Audio:
    """Serialize PortAudio discovery and playback. Never persist numeric indices."""

    def __init__(self, directory, settings=None):
        self.directory = directory
        self.settings = settings or Settings()
        self.preferred = self.settings.audio_output or None
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.outputs = {}
        self.default = None
        self.actual = None
        self.voices = []
        self.last_voice = None

    def _cue(self, name):
        voice = "FAIL"
        if name != "FAIL":
            count = CHOICES.index(name) + 1
            if not self.voices:
                self.voices = list(VOICES)
                random.shuffle(self.voices)
                if self.voices[-1] == self.last_voice:
                    self.voices[0], self.voices[-1] = self.voices[-1], self.voices[0]
            voice = self.last_voice = self.voices.pop()
        with wave.open(str(SOUNDS / f"{voice}.wav"), "rb") as src:
            rate = src.getframerate()
            note = src.readframes(src.getnframes())
        if name == "FAIL":
            return rate, note
        # Reuse the same variation within a cue; the pauses stay at fixed lengths.
        note = _vary_note(note)
        parts = [note]
        for beat in range(1, count):
            gap = 0.15 if beat % 2 == 0 else 0.065
            parts.extend((bytes(2 * int(rate * gap)), note))
        return rate, b"".join(parts)

    def select(self, name):
        previous = self.settings.audio_output
        self.settings.audio_output = name or ""
        try:
            self.settings.save(self.directory)
        except Exception:
            self.settings.audio_output = previous
            raise
        self.preferred = name

    def _discover(self):
        # PortAudio snapshots endpoint IDs at initialization. No streams are open here.
        sd._terminate()
        sd._initialize()
        hosts = sd.query_hostapis()
        target = "Windows WASAPI" if sys.platform == "win32" else "Core Audio"
        host = next((h for h in hosts if h["name"] == target), None)
        outputs = {}
        default_id = host["default_output_device"] if host else sd.default.device[1]
        self.default = None
        for index, device in enumerate(sd.query_devices()):
            if not device["max_output_channels"] or (host and index not in host["devices"]):
                continue
            name = device["name"]
            if name in outputs:
                name = f"{name} ({index})"
            outputs[name] = index
            if index == default_id:
                self.default = name
        self.outputs = outputs
        self.actual = next(iter(self._routes()), None)

    def _routes(self):
        return dict.fromkeys(n for n in (self.preferred, self.default, *self.outputs)
                             if n in self.outputs)

    def refresh(self):
        with self.lock:
            self._discover()

    def play(self, name):
        with self.lock:
            if self.closed.is_set():
                return
            self._discover()
            rate, data = self._cue(name)
            for route in self._routes():
                try:
                    settings = sd.WasapiSettings(auto_convert=True) if sys.platform == "win32" else None
                    with sd.RawOutputStream(device=self.outputs[route], samplerate=rate,
                                            channels=1, dtype="int16", extra_settings=settings) as stream:
                        for i in range(0, len(data), 2048):
                            if self.closed.is_set():
                                stream.abort()
                                return
                            stream.write(data[i:i+2048])
                    self.actual = route
                    return
                except sd.PortAudioError:
                    continue
            self.actual = None
            raise OSError("No output device")
