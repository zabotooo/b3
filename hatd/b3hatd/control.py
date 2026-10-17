"""Only one client controls the robot; it must keep pinging."""

import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


class ControlManager:
    def __init__(self, stop_everything: Callable[[], Awaitable[None]],
                 on_change: Callable[[str | None], None] | None = None,
                 timeout: float = 3.0, clock: Callable[[], float] = time.monotonic):
        self._stop_everything = stop_everything
        self._on_change = on_change
        self.timeout = timeout
        self._clock = clock
        self.holder: str | None = None
        self._last_ping = 0.0

    def _changed(self) -> None:
        if self._on_change:
            self._on_change(self.holder)

    async def claim(self, cid: str) -> None:
        self._last_ping = self._clock()
        if self.holder == cid:
            return
        previous, self.holder = self.holder, cid
        try:
            if previous is not None:
                await self._stop_everything()  # the new holder starts from a stopped robot
        finally:
            self._changed()

    def is_controller(self, cid: str | None) -> bool:
        return cid is not None and cid == self.holder

    def ping(self, cid: str) -> None:
        if self.is_controller(cid):
            self._last_ping = self._clock()

    async def release(self, cid: str, stop: bool) -> None:
        if not self.is_controller(cid):
            return
        self.holder = None
        try:
            if stop:
                await self._stop_everything()
        finally:
            self._changed()

    async def check(self) -> bool:
        if self.holder is None or self._clock() - self._last_ping <= self.timeout:
            return False
        await self.release(self.holder, stop=True)
        return True

    async def run(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.check()
            except Exception:
                log.exception("control watchdog failed")
