"""Plays project sounds and beeps on the Pi's audio output via aplay."""

import asyncio
import hashlib
import os
import re
from pathlib import Path

from aiohttp import web

from .errors import B3Error
from .keys import SOUND
from .tone import note_to_hz, write_tone

_MD5 = re.compile(r"^[0-9a-f]{32}$")
BEEP_FOREVER_S = 30.0
MAX_BEEPS = 50


class SubprocessRunner:
    async def spawn(self, args: list[str]):
        return await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

    async def run(self, args: list[str]) -> int:
        proc = await self.spawn(args)
        return await proc.wait()


def _check_md5(md5: str) -> None:
    if not isinstance(md5, str) or not _MD5.match(md5):
        raise B3Error("bad_args", "Invalid sound id")


class SoundPlayer:
    def __init__(self, cache_dir: Path, runner=None, device: str | None = None,
                 mixer_card: str | None = None, mixer_control: str | None = None,
                 beep_forever_s: float = BEEP_FOREVER_S):
        self.cache_dir = cache_dir
        self.beep_forever_s = beep_forever_s
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner or SubprocessRunner()
        self.device = device
        self.mixer_card = mixer_card
        self.mixer_control = mixer_control
        self.volume = 100
        self._playing: set = set()
        self._reapers: set[asyncio.Task] = set()

    def _path(self, md5: str) -> Path:
        _check_md5(md5)
        return self.cache_dir / f"{md5}.wav"

    def has(self, md5: str) -> bool:
        return self._path(md5).exists()

    def store(self, md5: str, data: bytes) -> None:
        path = self._path(md5)
        if hashlib.md5(data).hexdigest() != md5:
            raise B3Error("bad_args", "Checksum mismatch")
        if not (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
            raise B3Error("bad_args", "Only WAV sounds are supported")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    async def play(self, md5: str, wait: bool) -> None:
        path = self._path(md5)
        if not path.exists():
            raise B3Error("not_found", f"Sound {md5} is not uploaded")
        await self._play(path, wait)

    async def beep(self, note: int, duration: float | None) -> None:
        seconds = duration if duration is not None else self.beep_forever_s
        path = self.cache_dir / f"beep-{note}-{int(round(seconds * 1000))}.wav"
        if not path.exists():
            await asyncio.to_thread(write_tone, path, note_to_hz(note), seconds)
            self._prune_beeps()
        await self._play(path, wait=duration is not None)

    def _prune_beeps(self) -> None:
        """Keep only the newest MAX_BEEPS generated tones so the SD card cannot fill up."""
        beeps = sorted(self.cache_dir.glob("beep-*.wav"), key=lambda p: p.stat().st_mtime)
        for old in beeps[:-MAX_BEEPS]:
            old.unlink(missing_ok=True)

    async def _play(self, path: Path, wait: bool) -> None:
        args = ["aplay", "-q"] + (["-D", self.device] if self.device else []) + [str(path)]
        proc = await self.runner.spawn(args)
        self._playing.add(proc)
        if wait:
            try:
                await proc.wait()
            except asyncio.CancelledError:
                self._kill(proc)  # program stopped or client gone: silence it
                raise
            finally:
                self._playing.discard(proc)
        else:
            task = asyncio.ensure_future(self._reap(proc))
            self._reapers.add(task)
            task.add_done_callback(self._reapers.discard)

    async def _reap(self, proc) -> None:
        try:
            await proc.wait()
        finally:
            self._playing.discard(proc)

    @staticmethod
    def _kill(proc) -> None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    async def stop(self) -> None:
        for proc in list(self._playing):
            self._kill(proc)
        self._playing.clear()

    async def set_volume(self, value: int) -> None:
        self.volume = value
        if not self.mixer_control:
            return
        args = ["amixer", "-q"] + (["-c", self.mixer_card] if self.mixer_card else [])
        await self.runner.run(args + ["sset", self.mixer_control, f"{value}%"])


async def _put(request: web.Request) -> web.Response:
    request.app[SOUND].store(request.match_info["md5"], await request.read())
    return web.Response(status=204)


async def _head(request: web.Request) -> web.Response:
    return web.Response(status=200 if request.app[SOUND].has(request.match_info["md5"]) else 404)


def setup(app: web.Application) -> None:
    app.router.add_put("/api/sounds/{md5}", _put)
    app.router.add_head("/api/sounds/{md5}", _head)
