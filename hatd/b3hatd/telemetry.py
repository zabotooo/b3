"""Pushes port values (20 Hz) and device changes to all clients."""

import asyncio
import logging
from typing import Awaitable, Callable

from .backend import HatBackend
from .devices import PORTS, lookup

log = logging.getLogger(__name__)


def _describe(typeid: int | None) -> dict:
    if typeid is None:
        return {"typeid": None, "name": None, "kind": None}
    info = lookup(typeid)
    if info is None:
        return {"typeid": typeid, "name": f"Unknown device {typeid}", "kind": None}
    return {"typeid": typeid, "name": info.name, "kind": info.kind.value}


class TelemetryLoop:
    def __init__(self, backend: HatBackend, broadcast: Callable[[dict], Awaitable[None]],
                 interval: float = 0.05, vin_every: int = 20):
        self.backend = backend
        self.broadcast = broadcast
        self.interval = interval
        self.vin_every = vin_every
        self._known: dict[str, int | None] = {p: None for p in PORTS}
        self._steps = 0
        self._vin: float | None = None

    async def step(self) -> None:
        try:
            values = await self.backend.read()
            if self._steps % self.vin_every == 0:
                self._vin = await self.backend.vin()
        except Exception:
            log.exception("telemetry read failed")
            return
        finally:
            self._steps += 1
        types = self.backend.typeids()
        for p in PORTS:
            if types[p] != self._known[p]:
                self._known[p] = types[p]
                await self.broadcast({"type": "device", "port": p, **_describe(types[p])})
        ports = {}
        for p in PORTS:
            ports[p] = None if types[p] is None else {**_describe(types[p]), **values.get(p, {})}
        await self.broadcast({"type": "telemetry", "vin": self._vin, "ports": ports})

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                await self.step()
            except Exception:
                log.exception("telemetry step failed")
            next_tick = max(next_tick + self.interval, loop.time())
            await asyncio.sleep(next_tick - loop.time())
