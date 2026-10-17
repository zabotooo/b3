"""Sine-wave WAV files for beep blocks."""

import math
import os
import struct
import uuid
import wave
from pathlib import Path

RATE = 22050


def note_to_hz(note: int) -> float:
    """MIDI note number to frequency (69 = A4 = 440 Hz)."""
    return 440.0 * 2 ** ((note - 69) / 12)


def write_tone(path: Path, hz: float, seconds: float, rate: int = RATE) -> None:
    n = int(rate * seconds)
    step = 2 * math.pi * hz / rate
    frames = struct.pack(f"<{n}h", *(int(12000 * math.sin(step * i)) for i in range(n)))
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    os.replace(tmp, path)
