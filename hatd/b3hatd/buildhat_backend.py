"""HatBackend on top of the blocking `buildhat` library."""

import asyncio
import gc
import logging
import time
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


def _read_all(dev, readers: list) -> dict:
    values = {}
    for reader in readers:
        values.update(reader(dev))
    return values


# How long read() waits for this step's port reads; slower ones finish in the background
READ_WAIT = 0.03

# A healthy read answers within ~50 ms; one older than this means the HAT went silent
HAT_TIMEOUT = 3.0
_SILENT_MESSAGE = "Build HAT is not responding. B3 restarts it; reconnect in a moment."

# buildhat releases (coasts) a motor 0.2 s after a positional ramp, and a fast move then rolls
# on: up to 31 degrees past a go-to target and 148 degrees past a run-for-degrees target, measured
# on a Large Angular motor (hardware-notes.md "Motor stopping accuracy"). hatd holds the motor
# until it stands on the target, then releases it, so it stops within a few degrees.
SETTLE_TOLERANCE = 3  # degrees
SETTLE_LIMIT = 1.5  # seconds of holding at most
SETTLE_READS = 3  # consecutive reads on target and not moving

# buildhat's position PID (Kp 5, Kd 0.1) swings a motor 20-44 degrees past the target and back
# several times before it stands. Kp 8, Kd 0.6 stopped motors B and C with 0-3 degrees of
# overshoot and no swing (hardware-notes.md "Motor stopping accuracy").
POSITION_PID = "8 0 0.6"  # Kp Ki Kd


def damp_positional_moves(motor) -> None:
    """Make a buildhat Motor's run_to_position and run_for_degrees use POSITION_PID.
    The same ramp as buildhat's Motor._run_positional_ramp (0.6.0), other gains."""
    def damped_ramp(pos, newpos, speed):
        if motor._rpm:
            speed = motor._speed_process(speed)
        else:
            speed *= 0.05  # Collapse speed range to -5 to 5
        dur = abs((newpos - pos) / speed)
        cmd = (f"port {motor.port}; select 0 ; selrate {motor._interval}; "
               f"pid {motor.port} 0 1 s4 0.0027777778 0 {POSITION_PID} 3 0.01; "
               f"set ramp {pos} {newpos} {dur} 0\r")
        ftr = Future()
        motor._hat.rampftr[motor.port].append(ftr)
        motor._write(cmd)
        ftr.result()
        if motor._release:
            time.sleep(0.2)
            motor.coast()

    motor._run_positional_ramp = damped_ramp

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
        self._active = False  # a program runs: read every mode of multi-mode sensors
        self._silent = False  # the HAT stopped answering; hatd is about to restart
        self._fill: set[str] = set()  # ports to read in every mode at once (program just started)
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
        if self._silent:  # no new thread may block on a HAT that stopped answering
            raise B3Error("hat_not_responding", _SILENT_MESSAGE)
        return await asyncio.get_running_loop().run_in_executor(self._hw_pool, partial(fn, *args, **kwargs))

    # --- ports ------------------------------------------------------------
    def _open(self, port: str, kind: Kind):
        dev = getattr(self._buildhat, _CLASS_FOR_KIND[kind])(port)
        if kind in (Kind.MOTOR_ABS, Kind.MOTOR_REL):
            damp_positional_moves(dev)
        return dev

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
                    # opening and the first read wait on the firmware like any read: watch them too
                    dev, values = await asyncio.wait_for(self._attach(p, dev_info.kind), HAT_TIMEOUT)
                    self._values[p] = values
                    self._devices[p] = dev
                    self._kinds[p] = dev_info.kind
                    self._commanded[p] = dict(_COMMANDED_DEFAULTS.get(dev_info.kind, {}))
                except asyncio.TimeoutError:
                    self._unresponsive()
                except Exception as e:
                    # e.g. "Port already used" while the old object is still referenced;
                    # report the port empty so the next refresh tries again
                    log.warning("cannot open %s on port %s: %s", dev_info.name, p, e)
                    self._types[p] = None
                    # a woken thread's traceback keeps the old device in a reference cycle;
                    # buildhat frees the port only in Device.__del__
                    gc.collect()

    async def _attach(self, port: str, kind: Kind):
        dev = await self._run(self._open, port, kind)
        return dev, await self._run(_read_all, dev, self._readers(kind))

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
        except B3Error:
            raise
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

    def _readers(self, kind: Kind) -> list:
        # idle: one mode only, so a sensor's LED (Color & Distance) does not flash
        return _READERS[kind] if self._active else _READERS[kind][:1]

    # --- HatBackend -------------------------------------------------------
    def set_program_running(self, running: bool) -> None:
        if running and not self._active:
            # the idle modes' values are old: refresh every mode in the next read
            self._fill = {p for p, kind in self._kinds.items() if len(_READERS[kind]) > 1}
        self._active = running
        self.program_running = running

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
            readers = self._readers(self._kinds[p])
            busy = p in self._reading and not self._reading[p].done()
            if not readers or busy:  # a slow sensor read is still running: keep its last values
                continue
            if p in self._fill:
                self._fill.discard(p)
                reader = partial(_read_all, readers=_READERS[self._kinds[p]])
            else:
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
        self._silent = True
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
        raise B3Error("hat_not_responding", _SILENT_MESSAGE)

    async def motor_run_for_degrees(self, port, degrees, speed):
        self._require(port)
        gen = await self._begin(port)
        dev = self._require(port)
        start = {}

        def move():
            start["position"] = dev.get()[1]
            dev.run_for_degrees(degrees, speed=speed, blocking=True)

        def off_target(values):  # buildhat turns the other way for a negative speed
            return values[1] - (start["position"] + (degrees if speed >= 0 else -degrees))

        await self._blocking(port, gen, self._held_move, port, gen, dev, off_target, move)

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

        def off_target(values):
            return ((values[2] - position + 180) % 360) - 180

        await self._blocking(port, gen, self._held_move, port, gen, dev, off_target,
                             dev.run_to_position, position, speed=speed, blocking=True,
                             direction=_DIRECTIONS[direction])

    def _held_move(self, port: str, gen: int, dev, off_target, move, *args, **kwargs) -> None:
        """Run a positional buildhat move (in a thread) and hold the motor until it stands on
        the target, then release it so it can be turned by hand again."""
        dev.release = False
        try:
            move(*args, **kwargs)
            reads = 0
            deadline = time.monotonic() + SETTLE_LIMIT
            while reads < SETTLE_READS and time.monotonic() < deadline and self._generation[port] == gen:
                values = dev.get()
                steady = abs(off_target(values)) <= SETTLE_TOLERANCE and abs(values[0]) <= 1
                reads = reads + 1 if steady else 0
        finally:
            dev.release = True
            dev.coast()

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
        self.set_program_running(False)
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
