"""HatBackend on top of the blocking `buildhat` library."""

import asyncio
import gc
import logging
from concurrent.futures import Future, InvalidStateError, ThreadPoolExecutor
from functools import partial

from .backend import HatBackend
from .devices import ALL_MOTORS, PORTS, Kind, lookup
from .errors import B3Error

log = logging.getLogger(__name__)

_CLASS_FOR_KIND = {
    Kind.MOTOR_ABS: "Motor",
    Kind.MOTOR_REL: "Motor",
    Kind.MOTOR_PASSIVE: "PassiveMotor",
    Kind.LIGHT: "Light",
    Kind.MATRIX: "Matrix",
    Kind.COLOR: "ColorSensor",
    Kind.DISTANCE: "DistanceSensor",
    Kind.FORCE: "ForceSensor",
    Kind.COLOR_DISTANCE: "ColorDistanceSensor",
    Kind.WEDO_TILT: "TiltSensor",
    Kind.WEDO_MOTION: "MotionSensor",
}

# Each buildhat getter waits for the next data frame (~10 ms) and sensors switch modes
# per value (30-40 ms), so: motors are read with one get() ([speed, position,
# aposition]); multi-mode sensors read one value per step, round-robin.
_READERS: dict[Kind, list] = {
    Kind.MOTOR_ABS: [lambda d: dict(zip(("speed", "position", "aposition"), d.get()[:3]))],
    Kind.MOTOR_REL: [lambda d: dict(zip(("speed", "position"), d.get()[:2]))],
    Kind.MOTOR_PASSIVE: [],
    Kind.LIGHT: [],
    Kind.MATRIX: [],
    Kind.COLOR: [lambda d: {"color": d.get_color()},
                 lambda d: {"reflection": d.get_reflected_light()}],
    Kind.DISTANCE: [lambda d: {"distance_mm": d.get_distance()}],
    Kind.FORCE: [lambda d: {"force_n": d.get_force(), "pressed": d.is_pressed()}],
    Kind.COLOR_DISTANCE: [lambda d: {"color": d.get_color()},
                          lambda d: {"reflection": d.get_reflected_light()},
                          lambda d: {"distance": d.get_distance()}],
    Kind.WEDO_TILT: [lambda d: {"tilt": list(d.get_tilt())}],
    Kind.WEDO_MOTION: [lambda d: {"distance": d.get_distance()}],
}


def _read_all(dev, kind: Kind) -> dict:
    values = {}
    for reader in _READERS[kind]:
        values.update(reader(dev))
    return values


# How long read() waits for this step's port reads; slower ones finish in the background
READ_WAIT = 0.03

# A healthy read answers within ~50 ms; one older than this means the HAT went silent
HAT_TIMEOUT = 3.0

_DIRECTIONS = {"shortest": "shortest", "cw": "clockwise", "ccw": "anticlockwise"}


# Values hatd reports for devices it cannot read back (last commanded value)
_COMMANDED_DEFAULTS = {
    Kind.MOTOR_PASSIVE: {"power": 0},
    Kind.LIGHT: {"brightness": 0},
}


def reset_hat() -> None:
    """Restart the HAT into its bootloader, as buildhat does before loading new firmware.
    buildhat itself only resets on a firmware version mismatch, so a HAT whose firmware
    hung answers nothing and Hat() reports "HAT not found"."""
    import time
    from gpiozero import DigitalOutputDevice  # Pi only
    reset = DigitalOutputDevice(4)
    boot0 = DigitalOutputDevice(22)
    boot0.off()
    reset.off()
    time.sleep(0.01)
    reset.on()
    time.sleep(0.01)
    boot0.close()
    reset.close()
    time.sleep(0.5)


class _Waiters(list):
    """buildhat's per-port list of movement futures. hatd releases the futures of
    cut-short movements itself (see _release_waiters); when the firmware still reports
    such a movement done, buildhat's reader thread would pop an empty list and die,
    leaving every port unanswered until hatd restarts."""

    def pop(self, *args):
        try:
            return super().pop(*args)
        except IndexError:
            return Future()


class _LiveCallback:
    """A callback held strongly, shaped like the WeakMethod buildhat's callbackloop expects."""

    _alive = True

    def __init__(self, func):
        self._func = func

    def __call__(self):
        return self._func


def _live_callbacks(q) -> None:
    """buildhat's callbackloop checks a WeakMethod's _alive and then calls it; a device freed
    in between makes the call return None and kills the thread, after which no sensor reports
    values. Hand that thread only callbacks whose object is still alive, held strongly."""
    get = q.get

    def live_get(*args, **kwargs):
        while True:
            item = get(*args, **kwargs)
            if len(item) == 0:
                return item  # shutdown marker
            func = item[0]()
            if func is not None:
                return (_LiveCallback(func), item[1])
            q.task_done()

    q.get = live_get


class BuildHatBackend(HatBackend):
    """Motor commands on one port follow SPIKE semantics: a new command replaces the
    one running there, and stop/stop_all end it. Every command belongs to a port
    "generation"; anything that bumps the generation interrupts the older commands.
    """

    def __init__(self, reset=reset_hat):
        self._reset = reset
        self._buildhat = None
        self._hat = None
        self._types: dict[str, int | None] = {p: None for p in PORTS}
        self._devices: dict[str, object] = {}
        self._kinds: dict[str, Kind] = {}
        self._commanded: dict[str, dict] = {}
        self._values: dict[str, dict] = {}
        self._turn: dict[str, int] = {p: 0 for p in PORTS}
        # one reader thread per port, separate from the pool that runs motor commands
        self._read_pool = ThreadPoolExecutor(max_workers=len(PORTS), thread_name_prefix="b3-read")
        self._reading: dict[str, asyncio.Future] = {}
        # all blocking buildhat calls; aiohttp's default pool stays free for files and logins
        self._hw_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="b3-hw")
        self._read_started: dict[str, float] = {}
        self._generation: dict[str, int] = {p: 0 for p in PORTS}
        self._stops: dict[str, set[asyncio.Event]] = {p: set() for p in PORTS}
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        import buildhat  # Pi only
        self._buildhat = buildhat
        try:
            self._hat = await self._run(buildhat.Hat)  # loads firmware on first run
        except Exception as e:
            if "HAT not found" not in str(e):
                raise
            log.warning("Build HAT not answering; resetting it")
            await self._run(self._reset)
            self._hat = await self._run(buildhat.Hat)
        hat = buildhat.devices.Device._instance
        for lists in (hat.rampftr, hat.pulseftr):
            for i, pending in enumerate(lists):
                lists[i] = _Waiters(pending)
        _live_callbacks(hat.cbqueue)
        await self._refresh()

    async def close(self) -> None:
        for p in PORTS:
            await self._settle(p)
        self._devices.clear()
        self._kinds.clear()
        self._read_pool.shutdown(wait=False)
        self._hw_pool.shutdown(wait=False)

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(self._hw_pool, partial(fn, *args, **kwargs))

    # --- ports ------------------------------------------------------------
    def _open(self, port: str, kind: Kind):
        return getattr(self._buildhat, _CLASS_FOR_KIND[kind])(port)

    async def _refresh(self) -> None:
        async with self._lock:
            info = await self._run(self._hat.get)
            for p in PORTS:
                typeid = info[p]["typeid"]
                typeid = None if typeid == -1 else typeid
                if typeid == self._types[p]:
                    continue
                self._types[p] = typeid
                self._devices.pop(p, None)  # frees the port in buildhat (Device.__del__)
                self._kinds.pop(p, None)
                self._commanded.pop(p, None)
                self._values.pop(p, None)
                self._interrupt(p)
                self._release_waiters(p)
                self._fail_port_waiters(p, RuntimeError(f"port {p}: device changed"))
                self._reading.pop(p, None)
                dev_info = lookup(typeid)
                if dev_info is None:
                    continue
                try:
                    dev = await self._run(self._open, p, dev_info.kind)
                    self._values[p] = await self._run(_read_all, dev, dev_info.kind)
                    self._devices[p] = dev
                    self._kinds[p] = dev_info.kind
                    self._commanded[p] = dict(_COMMANDED_DEFAULTS.get(dev_info.kind, {}))
                except Exception as e:
                    # e.g. "Port already used" while the old object is still referenced;
                    # report the port empty so the next refresh tries again
                    log.warning("cannot open %s on port %s: %s", dev_info.name, p, e)
                    self._types[p] = None
                    # a woken thread's traceback keeps the old device in a reference cycle;
                    # buildhat frees the port only in Device.__del__
                    gc.collect()

    def _require(self, port: str):
        dev = self._devices.get(port)
        if dev is None:
            raise B3Error("no_device", f"Port {port}: no device", port=port)
        return dev

    def _remember(self, port: str, **values) -> None:
        if port in self._commanded:
            self._commanded[port].update(values)

    async def _call(self, port: str, fn, *args, **kwargs):
        """Run a blocking buildhat call in a thread; library errors name the port."""
        try:
            return await self._run(fn, *args, **kwargs)
        except Exception as e:
            raise B3Error("hardware_error", f"Port {port}: {e}", port=port) from e

    # --- interruption -----------------------------------------------------
    def _interrupt(self, port: str) -> None:
        self._generation[port] += 1
        for ev in list(self._stops[port]):
            ev.set()

    def _fail_port_waiters(self, port: str, error: Exception) -> None:
        """Wake every thread waiting on this port's firmware replies with `error`.
        buildhat waits on these futures without a timeout; a device that dropped off
        (or a silent HAT) would hold such a thread, and the old device object, forever."""
        hat = self._buildhat.devices.Device._instance
        i = PORTS.index(port)
        for lists in (hat.portftr, hat.rampftr, hat.pulseftr):
            pending = list(lists[i])
            lists[i].clear()
            for ftr in pending:
                try:
                    ftr.set_exception(error)
                except InvalidStateError:
                    pass

    def _check(self, port: str, gen: int) -> None:
        if self._generation[port] != gen:
            raise B3Error("interrupted", f"Port {port}: stopped", port=port)

    def _release_waiters(self, port: str) -> None:
        """buildhat never resolves a ramp/pulse future when the movement is cut short
        (coast, a new command, unplug), so the blocked thread would hang forever and
        exhaust the thread pool. Whoever cuts a movement short calls this."""
        if self._buildhat is None:
            return
        hat = self._buildhat.devices.Device._instance
        idx = PORTS.index(port)
        for pending in (hat.rampftr[idx], hat.pulseftr[idx]):
            while pending:
                try:
                    pending.pop().set_result(None)
                except (IndexError, InvalidStateError):
                    pass

    async def _settle(self, port: str) -> None:
        """Wait for a released thread to finish its trailing coast() before a new command."""
        work = self._inflight.get(port)
        if work is not None and not work.done():
            await asyncio.wait({work}, timeout=2)

    async def _begin(self, port: str) -> int:
        """Prepare a new motor command: end what runs on the port, wait for its thread,
        and return the new command's generation. A stop meanwhile raises interrupted."""
        work = self._inflight.get(port)
        busy = (work is not None and not work.done()) or self._stops[port]
        self._interrupt(port)  # every command gets its own generation (stop_all relies on it)
        if busy:
            self._release_waiters(port)
        gen = self._generation[port]
        await self._settle(port)
        self._check(port, gen)
        return gen

    async def _halt(self, port: str) -> None:
        """Stop the motor on `port` and free the thread of a cut-short movement."""
        self._interrupt(port)
        dev = self._devices.get(port)
        if dev is not None:
            await self._call(port, dev.stop)
        self._release_waiters(port)
        self._remember(port, power=0)

    async def _blocking(self, port: str, gen: int, fn, *args, **kwargs) -> None:
        """Run a blocking buildhat movement; raise `interrupted` if it was cut short."""
        stop = asyncio.Event()
        self._stops[port].add(stop)
        work = asyncio.ensure_future(self._call(port, fn, *args, **kwargs))
        work.add_done_callback(lambda f: f.cancelled() or f.exception())
        self._inflight[port] = work
        stopped = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({work, stopped}, return_when=asyncio.FIRST_COMPLETED)
            self._check(port, gen)
            await work
        finally:
            stopped.cancel()
            self._stops[port].discard(stop)

    # --- HatBackend -------------------------------------------------------
    def typeids(self) -> dict[str, int | None]:
        return dict(self._types)

    async def read(self) -> dict[str, dict]:
        await self._refresh()
        loop = asyncio.get_running_loop()
        for p, fut in list(self._reading.items()):
            if not fut.done() and loop.time() - self._read_started.get(p, loop.time()) > HAT_TIMEOUT:
                self._unresponsive()
        started = []
        for p, dev in list(self._devices.items()):
            readers = _READERS[self._kinds[p]]
            busy = p in self._reading and not self._reading[p].done()
            if not readers or busy:  # a slow sensor read is still running: keep its last values
                continue
            reader = readers[self._turn[p] % len(readers)]
            self._turn[p] += 1
            fut = loop.run_in_executor(self._read_pool, reader, dev)
            fut.add_done_callback(partial(self._store, p, dev))
            self._reading[p] = fut
            self._read_started[p] = loop.time()
            started.append(fut)
        if started:
            await asyncio.wait(started, timeout=READ_WAIT)
        devices = list(self._devices)
        return {p: {**self._values.get(p, {}), **self._commanded.get(p, {})} for p in devices}

    def _store(self, port: str, dev, fut: asyncio.Future) -> None:
        if fut.cancelled():
            return
        if fut.exception() is not None:  # device unplugged between refresh and read
            log.debug("read %s failed: %s", port, fut.exception())
            return
        if self._devices.get(port) is dev and port in self._values:
            self._values[port].update(fut.result())

    async def vin(self) -> float:
        try:
            return await asyncio.wait_for(self._run(self._hat.get_vin), HAT_TIMEOUT)
        except asyncio.TimeoutError:
            self._unresponsive()

    def _unresponsive(self) -> None:
        """The HAT stopped answering: wake every thread waiting on it, then give up."""
        log.error("Build HAT not responding")
        error = RuntimeError("Build HAT not responding")
        for p in PORTS:
            self._fail_port_waiters(p, error)
        hat = self._buildhat.devices.Device._instance
        pending = list(hat.vinftr)
        hat.vinftr.clear()
        for ftr in pending:
            try:
                ftr.set_exception(error)
            except InvalidStateError:
                pass
        raise B3Error("hat_not_responding", "Build HAT is not responding. B3 restarts it; reconnect in a moment.")

    async def motor_run_for_degrees(self, port, degrees, speed):
        self._require(port)
        gen = await self._begin(port)
        dev = self._require(port)
        await self._blocking(port, gen, dev.run_for_degrees, degrees, speed=speed, blocking=True)

    async def motor_run_for_seconds(self, port, seconds, speed):
        self._require(port)
        gen = await self._begin(port)
        dev = self._require(port)
        if self._kinds[port] is not Kind.MOTOR_PASSIVE:
            await self._blocking(port, gen, dev.run_for_seconds, seconds, speed=speed, blocking=True)
            return
        stop = asyncio.Event()
        self._stops[port].add(stop)  # registered before start(): a stop meanwhile is seen
        try:
            await self._call(port, dev.start, speed)
            self._remember(port, power=speed)
            if self._generation[port] != gen:
                await self._call(port, dev.stop)  # stopped while starting
                self._remember(port, power=0)
                self._check(port, gen)
            try:
                await asyncio.wait_for(stop.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                await self._call(port, dev.stop)
                self._remember(port, power=0)
                return
            # stopped or replaced: whoever interrupted owns the motor now
            self._check(port, gen)
        finally:
            self._stops[port].discard(stop)

    async def motor_start(self, port, speed):
        self._require(port)
        gen = await self._begin(port)
        dev = self._require(port)
        await self._call(port, dev.start, speed)
        self._remember(port, power=speed)
        if self._generation[port] != gen:  # a stop arrived while starting
            await self._call(port, dev.stop)
            self._remember(port, power=0)
            self._check(port, gen)

    async def motor_stop(self, port):
        self._require(port)
        await self._halt(port)

    async def motor_go_to(self, port, position, direction, speed):
        self._require(port)
        gen = await self._begin(port)
        dev = self._require(port)
        position = ((position + 180) % 360) - 180  # SPIKE 0..359 -> buildhat -180..179
        await self._blocking(port, gen, dev.run_to_position, position, speed=speed, blocking=True,
                             direction=_DIRECTIONS[direction])

    async def light_set(self, port, brightness):
        dev = self._require(port)
        if brightness == 0:
            await self._call(port, dev.off)
        else:
            await self._call(port, dev.brightness, brightness)
        self._remember(port, brightness=brightness)

    async def matrix_set(self, port, pixels):
        dev = self._require(port)
        rows = [pixels[0:3], pixels[3:6], pixels[6:9]]
        await self._call(port, dev.set_pixels, rows)

    async def sensor_lights(self, port, values):
        dev = self._require(port)
        await self._call(port, dev.eyes, *values)

    async def stop_all(self):
        # Interrupt every port before the first await: a command sent right after
        # stop_all (Run does that) must not be halted when stop_all reaches its port.
        gens = {}
        for p in PORTS:
            self._interrupt(p)
            gens[p] = self._generation[p]
        for p in PORTS:
            if self._kinds.get(p) not in ALL_MOTORS or self._generation[p] != gens[p]:
                continue  # not a motor, or a newer command already owns the port
            try:
                dev = self._devices.get(p)
                if dev is not None:
                    await self._call(p, dev.stop)
                self._release_waiters(p)
                self._remember(p, power=0)
            except Exception:
                log.exception("stop %s failed", p)
