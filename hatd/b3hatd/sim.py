"""In-memory Build HAT for tests and development without hardware."""

import asyncio

from .backend import HatBackend
from .devices import ALL_MOTORS, PORTS, Kind, lookup
from .errors import B3Error

DEFAULT_VALUES: dict[Kind, dict] = {
    Kind.MOTOR_ABS: {"position": 0, "aposition": 0, "speed": 0},
    Kind.MOTOR_REL: {"position": 0, "speed": 0},
    Kind.MOTOR_PASSIVE: {"power": 0},
    Kind.LIGHT: {"brightness": 0},
    Kind.MATRIX: {},
    Kind.COLOR: {"color": "none", "reflection": 0},
    Kind.DISTANCE: {"distance_mm": -1},
    Kind.FORCE: {"force_n": 0.0, "pressed": False},
    Kind.COLOR_DISTANCE: {"color": "none", "reflection": 0, "distance": 0},
    Kind.WEDO_TILT: {"tilt": [0, 0]},
    Kind.WEDO_MOTION: {"distance": 0},
}


def _wrap(angle: float) -> float:
    """Normalise to -180..179."""
    return ((angle + 180) % 360) - 180


class SimBackend(HatBackend):
    def __init__(self, max_dps: float = 1000.0, vin: float = 8.0):
        self.max_dps = max_dps
        self._vin = vin
        self._types: dict[str, int | None] = {p: None for p in PORTS}
        self._waiters: dict[str, set[asyncio.Event]] = {p: set() for p in PORTS}
        self.values: dict[str, dict] = {}
        self.calls: list[tuple] = []

    # --- test helpers -------------------------------------------------
    def attach(self, port: str, typeid: int, **values) -> None:
        self._types[port] = typeid
        info = lookup(typeid)
        base = dict(DEFAULT_VALUES[info.kind]) if info else {}
        base.update(values)
        self.values[port] = base

    def detach(self, port: str) -> None:
        self._types[port] = None
        self.values.pop(port, None)
        self._interrupt(port)

    def set_vin(self, vin: float) -> None:
        self._vin = vin

    # --- internals ----------------------------------------------------
    def _require(self, port: str) -> dict:
        if self._types[port] is None:
            raise B3Error("no_device", f"Port {port}: no device", port=port)
        return self.values[port]

    def _set_speed(self, port: str, speed: int) -> None:
        values = self.values.get(port, {})
        key = "power" if "power" in values else "speed"
        values[key] = speed

    def _interrupt(self, port: str) -> None:
        for ev in list(self._waiters[port]):
            ev.set()

    async def _wait(self, port: str, seconds: float) -> None:
        ev = asyncio.Event()
        self._waiters[port].add(ev)
        try:
            try:
                await asyncio.wait_for(ev.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                return
            raise B3Error("interrupted", f"Port {port}: stopped", port=port)
        finally:
            self._waiters[port].discard(ev)

    def _move(self, port: str, delta: float) -> None:
        values = self.values[port]
        values["position"] += delta
        if "aposition" in values:
            values["aposition"] = _wrap(values["aposition"] + delta)

    def _duration(self, degrees: float, speed: int) -> float:
        return abs(degrees) / (abs(speed) / 100 * self.max_dps)

    # --- HatBackend ---------------------------------------------------
    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def typeids(self) -> dict[str, int | None]:
        return dict(self._types)

    async def read(self) -> dict[str, dict]:
        return {p: dict(v) for p, v in self.values.items()}

    async def vin(self) -> float:
        return self._vin

    async def motor_run_for_degrees(self, port, degrees, speed):
        self._require(port)
        self.calls.append(("run_for_degrees", port, degrees, speed))
        self._set_speed(port, speed)
        await self._wait(port, self._duration(degrees, speed))
        self._move(port, degrees if speed > 0 else -degrees)
        self._set_speed(port, 0)

    async def motor_run_for_seconds(self, port, seconds, speed):
        self._require(port)
        self.calls.append(("run_for_seconds", port, seconds, speed))
        self._set_speed(port, speed)
        await self._wait(port, seconds)
        self._set_speed(port, 0)

    async def motor_start(self, port, speed):
        self._require(port)
        self.calls.append(("start", port, speed))
        self._set_speed(port, speed)

    async def motor_stop(self, port):
        self._require(port)
        self.calls.append(("stop", port))
        self._set_speed(port, 0)
        self._interrupt(port)

    async def motor_go_to(self, port, position, direction, speed):
        values = self._require(port)
        self.calls.append(("go_to", port, position, direction, speed))
        cw = (_wrap(position) - values["aposition"]) % 360
        if direction == "cw":
            delta = cw
        elif direction == "ccw":
            delta = cw - 360 if cw else 0
        else:
            delta = cw if cw <= 180 else cw - 360
        await self._wait(port, self._duration(delta, speed))
        self._move(port, delta)

    async def light_set(self, port, brightness):
        self._require(port)
        self.calls.append(("light_set", port, brightness))
        self.values[port]["brightness"] = brightness

    async def matrix_set(self, port, pixels):
        self._require(port)
        self.calls.append(("matrix_set", port, pixels))

    async def sensor_lights(self, port, values):
        self._require(port)
        self.calls.append(("sensor_lights", port, values))

    async def stop_all(self):
        self.calls.append(("stop_all",))
        for port in PORTS:
            info = lookup(self._types[port])
            if info and info.kind in ALL_MOTORS:
                self._set_speed(port, 0)
            self._interrupt(port)


class _FinishedProcess:
    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


class SilentRunner:
    """Sound runner for --sim: plays nothing, so a development machine needs no aplay."""

    async def spawn(self, args: list[str]) -> _FinishedProcess:
        return _FinishedProcess()

    async def run(self, args: list[str]) -> int:
        return 0
