"""BuildHatBackend logic against a fake `buildhat` module (runs on the PC).

The fake reproduces the buildhat quirk that matters: a blocking movement waits on a
future that only the firmware's "ramp done"/"pulse done" resolves, and a movement cut
short by coast(), start() or another movement never gets that message.
"""

import asyncio
import queue
import sys
import threading
import time
import types
import weakref
from concurrent.futures import Future, ThreadPoolExecutor

import pytest
import pytest_asyncio

from b3hatd.buildhat_backend import BuildHatBackend
from b3hatd.errors import B3Error


class FakeInstance:
    def __init__(self):
        self.rampftr = [[] for _ in range(4)]
        self.pulseftr = [[] for _ in range(4)]
        self.cbqueue = queue.Queue()
        self.portftr = [[] for _ in range(4)]
        self.vinftr = []


class FakeHat:
    types = {"A": 48, "B": -1, "C": -1, "D": -1}
    vin_hangs = False
    vin_released = False

    def get(self):
        return {p: {"typeid": t} for p, t in self.types.items()}

    def get_vin(self):
        if FakeHat.vin_hangs:
            ftr = Future()
            FakeMotor.instance.vinftr.append(ftr)
            try:
                ftr.result(timeout=10)
            except Exception:
                FakeHat.vin_released = True
                raise
        return 8.0


class FakeMotor:
    failures = 0
    instance: FakeInstance = None
    blocked = 0
    gets = 0
    lag = 0  # reads after a move that still report the old position (the motor is still moving)
    lock = threading.Lock()

    def __init__(self, port):
        if FakeMotor.failures:
            FakeMotor.failures -= 1
            raise RuntimeError("Port already used")
        self.idx = "ABCD".index(port)
        self.speed = 0
        self.epoch = 0
        self.log = []
        self.release = True  # buildhat: coast 0.2 s after a movement
        self.release_seen = None
        self.apos = 0
        self.pos = 0
        self._target = None  # (attribute, value) the motor reaches after `lag` more reads
        self._lag = 0

    # firmware simulation ------------------------------------------------
    def _move(self, lists, seconds):
        self.epoch += 1
        epoch = self.epoch
        ftr = Future()
        lists[self.idx].append(ftr)

        def firmware_done():
            if self.epoch == epoch and ftr in lists[self.idx]:
                lists[self.idx].remove(ftr)
                ftr.set_result(None)

        threading.Timer(seconds, firmware_done).start()
        with FakeMotor.lock:
            FakeMotor.blocked += 1
        try:
            try:
                ftr.result(timeout=5)  # real buildhat waits forever; bounded so tests end
            except TimeoutError:
                return
            if self.release:
                time.sleep(0.1)  # buildhat: time.sleep(0.2); self.coast()
                self.coast()
            else:
                self.speed = 0  # holding at the target
        finally:
            with FakeMotor.lock:
                FakeMotor.blocked -= 1

    # buildhat Motor API ---------------------------------------------------
    def run_for_degrees(self, degrees, speed=None, blocking=True):
        self.log.append(("run_for_degrees", degrees, speed))
        self.release_seen = self.release
        self._target, self._lag = ("pos", self.pos + (degrees if speed >= 0 else -degrees)), FakeMotor.lag
        self.speed = speed
        self._move(FakeMotor.instance.rampftr, degrees / (abs(speed) * 10))

    def run_for_seconds(self, seconds, speed=None, blocking=True):
        self.log.append(("run_for_seconds", seconds, speed))
        self.speed = speed
        self._move(FakeMotor.instance.pulseftr, seconds)

    def run_to_position(self, degrees, speed=None, blocking=True, direction="shortest"):
        if degrees < -180 or degrees > 180:
            raise RuntimeError("Invalid angle")
        self.log.append(("run_to_position", degrees, speed, direction))
        self.release_seen = self.release
        self._target, self._lag = ("apos", degrees), FakeMotor.lag
        self._move(FakeMotor.instance.rampftr, 0.05)

    def start(self, speed=None):
        self.epoch += 1
        self.log.append(("start", speed))
        self.speed = speed

    def stop(self):
        self.coast()

    def coast(self):
        self.epoch += 1
        self.log.append(("coast",))
        self.speed = 0

    def get(self):
        FakeMotor.gets += 1
        if self._target is not None:
            if self._lag > 0:
                self._lag -= 1
            else:
                setattr(self, *self._target)
                self._target = None
        return [self.speed, self.pos, self.apos]

    def get_position(self):
        raise AssertionError("each getter waits for a data frame; read all with get()")

    get_aposition = get_speed = get_position


class FakeColorDistance:
    delay = 0.0
    reflection = 40

    def __init__(self, port):
        self.calls = []

    def get_color(self):
        self.calls.append("color")
        return "red"

    def get_reflected_light(self):
        self.calls.append("reflection")
        time.sleep(FakeColorDistance.delay)  # mode switch on the real sensor: 30-40 ms
        return FakeColorDistance.reflection

    def get_distance(self):
        self.calls.append("distance")
        return 5


class FakeHangingColorDistance:
    """Like buildhat: the port is free again only when the object is deleted, and a
    getter waits on a portftr future that only the firmware resolves."""
    used: set = set()
    hang = False

    def __init__(self, port):
        self.idx = "ABCD".index(port)
        if self.idx in FakeHangingColorDistance.used:
            raise RuntimeError("Port already used")
        FakeHangingColorDistance.used.add(self.idx)

    def __del__(self):
        FakeHangingColorDistance.used.discard(self.idx)

    def _value(self, value):
        if FakeHangingColorDistance.hang:
            ftr = Future()
            FakeMotor.instance.portftr[self.idx].append(ftr)
            ftr.result(timeout=10)  # real buildhat waits forever; bounded so tests end
        return value

    def get_color(self):
        return self._value("red")

    def get_reflected_light(self):
        return self._value(40)

    def get_distance(self):
        return self._value(5)


class FakePassiveMotor:
    def __init__(self, port):
        self.speed = 0

    def start(self, speed=None):
        time.sleep(0.2)  # slow serial write, so a stop can arrive meanwhile
        self.speed = speed

    def stop(self):
        self.speed = 0


class FakeLight:
    def __init__(self, port):
        self.level = 0

    def brightness(self, b):
        self.level = b

    def off(self):
        self.level = 0


@pytest.fixture
def fake_buildhat(monkeypatch):
    instance = FakeInstance()
    module = types.SimpleNamespace(
        Hat=FakeHat, Motor=FakeMotor, PassiveMotor=FakePassiveMotor, Light=FakeLight,
        ColorDistanceSensor=FakeColorDistance,
        devices=types.SimpleNamespace(Device=types.SimpleNamespace(_instance=instance)))
    monkeypatch.setitem(sys.modules, "buildhat", module)
    monkeypatch.setattr(FakeHat, "types", {"A": 48, "B": -1, "C": -1, "D": -1})
    monkeypatch.setattr(FakeHat, "vin_hangs", False)
    monkeypatch.setattr(FakeHat, "vin_released", False)
    FakeMotor.failures = 0
    FakeMotor.instance = instance
    FakeMotor.blocked = 0
    monkeypatch.setattr(FakeMotor, "lag", 0)
    return module


@pytest_asyncio.fixture
async def hat(fake_buildhat):
    backend = BuildHatBackend()
    await backend.start()
    yield backend
    await backend.stop_all()
    await backend.close()


async def _no_blocked_threads():
    for _ in range(40):
        if FakeMotor.blocked == 0:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_device_open_failure_is_retried(fake_buildhat):
    FakeMotor.failures = 1
    backend = BuildHatBackend()
    await backend.start()
    assert backend.typeids()["A"] is None
    values = await backend.read()
    assert backend.typeids()["A"] == 48
    assert values["A"] == {"position": 0, "aposition": 0, "speed": 0}


async def test_stop_frees_thread_of_cut_short_move(hat):
    task = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))
    await asyncio.sleep(0.1)
    await hat.motor_stop("A")
    with pytest.raises(B3Error) as e:
        await asyncio.wait_for(task, 1)
    assert e.value.code == "interrupted"
    assert await _no_blocked_threads()


async def test_cancelled_waiter_then_stop_all_frees_thread(hat):
    # client disconnect: the command task is cancelled, then stop_all runs
    task = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))
    await asyncio.sleep(0.1)
    task.cancel()
    await hat.stop_all()
    assert await _no_blocked_threads()


async def test_new_command_replaces_running_move(hat):
    task = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))
    await asyncio.sleep(0.1)
    await asyncio.wait_for(hat.motor_start("A", 30), 2)
    with pytest.raises(B3Error) as e:
        await asyncio.wait_for(task, 1)
    assert e.value.code == "interrupted"
    assert await _no_blocked_threads()
    await asyncio.sleep(0.2)
    assert (await hat.read())["A"]["speed"] == 30  # the old move's trailing coast came first


async def test_second_run_for_replaces_first(hat):
    first = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))
    await asyncio.sleep(0.1)
    await asyncio.wait_for(hat.motor_run_for_degrees("A", 90, 100), 2)
    with pytest.raises(B3Error):
        await asyncio.wait_for(first, 1)
    assert await _no_blocked_threads()


async def test_stop_while_new_command_settles_is_not_lost(hat):
    # run_for_seconds still ends with buildhat's own trailing coast, which the new command waits for
    first = asyncio.create_task(hat.motor_run_for_seconds("A", 36, 10))
    await asyncio.sleep(0.1)
    second = asyncio.create_task(hat.motor_start("A", 30))  # settles ~0.1 s
    await asyncio.sleep(0.02)
    await hat.stop_all()
    for task in (first, second):
        with pytest.raises(B3Error):
            await asyncio.wait_for(task, 1)
    await asyncio.sleep(0.2)
    assert (await hat.read())["A"]["speed"] == 0


async def test_command_sent_right_after_stop_all_is_not_cut_short(fake_buildhat, monkeypatch):
    # Run sends stop_all and then the program's first command without waiting;
    # stop_all must not halt a port whose new command began meanwhile.
    monkeypatch.setattr(FakeHat, "types", {"A": 48, "B": 48, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    stop = asyncio.create_task(backend.stop_all())
    started = time.monotonic()
    run = asyncio.create_task(backend.motor_run_for_degrees("B", 900, 100))  # ~0.9 s
    await asyncio.wait_for(stop, 2)
    await asyncio.wait_for(run, 3)
    assert time.monotonic() - started > 0.8, "stop_all cut the new move short"
    await backend.close()


async def test_late_ramp_done_does_not_kill_the_reader_thread(hat):
    # The firmware can report "ramp done" for a movement whose waiter hatd already
    # released; buildhat's reader thread then pops an empty list and dies.
    instance = hat._buildhat.devices.Device._instance
    late = instance.rampftr[0].pop()
    late.set_result(True)
    instance.pulseftr[3].pop().set_result(True)


async def test_callback_of_a_freed_device_does_not_kill_the_callback_thread(hat):
    # buildhat's callbackloop checks a WeakMethod's _alive flag and then calls it; when the
    # device is freed in between, the call returns None and the thread dies, so no sensor
    # reports values any more. hatd's queue hands out live callbacks only.
    class Sensor:
        def __init__(self):
            self.got = []

        def on_data(self, data):
            self.got.append(data)

    q = hat._buildhat.devices.Device._instance.cbqueue
    gone = Sensor()
    q.put((weakref.WeakMethod(gone.on_data), [1]))
    del gone  # freed after queuing, before the callback thread takes it
    live = Sensor()
    q.put((weakref.WeakMethod(live.on_data), [2]))
    cb = q.get()
    assert cb[0]._alive
    cb[0]()(cb[1])
    assert live.got == [[2]]
    q.put(())
    assert q.get() == ()  # buildhat's shutdown marker passes through


async def test_stop_during_passive_start_is_not_lost(fake_buildhat, monkeypatch):
    monkeypatch.setattr(FakeHat, "types", {"A": -1, "B": 2, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    task = asyncio.create_task(backend.motor_run_for_seconds("B", 60, 50))
    await asyncio.sleep(0.05)  # inside the slow start()
    await backend.stop_all()
    with pytest.raises(B3Error):
        await asyncio.wait_for(task, 1)
    assert backend._devices["B"].speed == 0


async def test_go_to_accepts_spike_positions(hat):
    await asyncio.wait_for(hat.motor_go_to("A", 270, "shortest", 50), 2)
    assert ("run_to_position", -90, 50, "shortest") in hat._devices["A"].log


async def test_library_errors_name_the_port(hat):
    def boom(speed=None):
        raise RuntimeError("serial glitch")

    hat._devices["A"].start = boom
    with pytest.raises(B3Error) as e:
        await hat.motor_start("A", 10)
    assert e.value.code == "hardware_error"
    assert e.value.port == "A"


async def test_passive_motor_and_light_report_commanded_values(fake_buildhat, monkeypatch):
    monkeypatch.setattr(FakeHat, "types", {"A": 8, "B": 2, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    assert await backend.read() == {"A": {"brightness": 0}, "B": {"power": 0}}
    await backend.light_set("A", 40)
    await backend.motor_start("B", -60)
    assert await backend.read() == {"A": {"brightness": 40}, "B": {"power": -60}}
    await backend.motor_stop("B")
    assert (await backend.read())["B"] == {"power": 0}


async def test_motor_is_read_with_one_get(hat):
    FakeMotor.gets = 0
    values = await hat.read()
    assert values["A"] == {"speed": 0, "position": 0, "aposition": 0}
    assert FakeMotor.gets == 1


async def test_multi_mode_sensor_reads_one_value_per_step(fake_buildhat, monkeypatch):
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    sensor = backend._devices["A"]
    assert sensor.calls == ["color"]  # filled once on attach, idle: first mode only
    backend.set_program_running(True)
    await backend.read()  # program start: every mode at once
    sensor.calls.clear()
    for _ in range(3):
        values = await backend.read()
        assert values["A"] == {"color": "red", "reflection": 40, "distance": 5}
    assert sorted(sensor.calls) == ["color", "distance", "reflection"]  # one per step


async def test_slow_sensor_does_not_hold_up_telemetry(fake_buildhat, monkeypatch):
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": 48, "C": -1, "D": -1})
    monkeypatch.setattr(FakeColorDistance, "reflection", 40)
    backend = BuildHatBackend()
    await backend.start()
    backend.set_program_running(True)
    monkeypatch.setattr(FakeColorDistance, "delay", 0.3)
    monkeypatch.setattr(FakeColorDistance, "reflection", 77)
    slowest = 0.0
    for _ in range(12):
        t0 = time.monotonic()
        values = await backend.read()
        slowest = max(slowest, time.monotonic() - t0)
        assert "speed" in values["B"]
        await asyncio.sleep(0.05)
    assert slowest < 0.05
    assert values["A"]["reflection"] == 77  # the slow value still arrives
    await backend.close()


async def test_device_that_dropped_off_while_reading_is_opened_again(fake_buildhat, monkeypatch):
    monkeypatch.setattr(fake_buildhat, "ColorDistanceSensor", FakeHangingColorDistance)
    monkeypatch.setattr(FakeHangingColorDistance, "used", set())
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    FakeHangingColorDistance.hang = True
    try:
        await backend.read()  # a read starts and waits for a frame that never comes
        FakeHat.types = {"A": -1, "B": -1, "C": -1, "D": -1}  # sensor drops off
        await backend.read()
        FakeHangingColorDistance.hang = False
        FakeHat.types = {"A": 37, "B": -1, "C": -1, "D": -1}  # and comes back
        for _ in range(20):
            await backend.read()
            if backend.typeids()["A"] == 37:
                break
            await asyncio.sleep(0.05)
        assert backend.typeids()["A"] == 37
        assert "A" in backend._devices
    finally:
        FakeHangingColorDistance.hang = False
        await backend.close()


class _NoDefaultPool(ThreadPoolExecutor):
    def submit(self, *args, **kwargs):
        raise AssertionError("buildhat call on the event loop's default thread pool")


async def test_buildhat_calls_leave_the_default_pool_free(hat):
    # aiohttp serves files through the default pool; stuck hardware calls must not starve it
    asyncio.get_running_loop().set_default_executor(_NoDefaultPool(max_workers=1))
    await hat.read()
    await hat.vin()
    await hat.motor_run_for_degrees("A", 90, 50)
    await hat.motor_start("A", 20)
    await hat.motor_stop("A")
    await hat.stop_all()


async def test_unresponsive_hat_frees_threads_and_reports(fake_buildhat, monkeypatch):
    monkeypatch.setattr("b3hatd.buildhat_backend.HAT_TIMEOUT", 0.3)
    monkeypatch.setattr(fake_buildhat, "ColorDistanceSensor", FakeHangingColorDistance)
    monkeypatch.setattr(FakeHangingColorDistance, "used", set())
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    FakeHangingColorDistance.hang = True
    try:
        with pytest.raises(B3Error) as e:
            for _ in range(40):  # telemetry steps until the stuck read is older than HAT_TIMEOUT
                await backend.read()
                await asyncio.sleep(0.05)
        assert e.value.code == "hat_not_responding"
        assert fake_buildhat.devices.Device._instance.portftr[0] == []
    finally:
        FakeHangingColorDistance.hang = False
        await backend.close()


async def test_silent_vin_wakes_its_thread_and_reports(hat, monkeypatch):
    monkeypatch.setattr("b3hatd.buildhat_backend.HAT_TIMEOUT", 0.3)
    FakeHat.vin_hangs = True
    with pytest.raises(B3Error) as e:
        await hat.vin()
    assert e.value.code == "hat_not_responding"
    await asyncio.sleep(0.1)
    assert FakeHat.vin_released, "the thread stuck in get_vin was woken"


async def test_long_movement_is_not_a_hang(hat, monkeypatch):
    monkeypatch.setattr("b3hatd.buildhat_backend.HAT_TIMEOUT", 0.3)
    task = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))  # 36 s in the fake
    for _ in range(12):
        await hat.read()
        await asyncio.sleep(0.05)
    assert not task.done()
    await hat.motor_stop("A")
    with pytest.raises(B3Error):
        await task


class FakeHatNotFoundOnce(FakeHat):
    failures = 1

    def __init__(self):
        if FakeHatNotFoundOnce.failures:
            FakeHatNotFoundOnce.failures -= 1
            raise RuntimeError("HAT not found")


async def test_hat_not_found_is_reset_and_retried(fake_buildhat, monkeypatch):
    monkeypatch.setattr(fake_buildhat, "Hat", FakeHatNotFoundOnce)
    monkeypatch.setattr(FakeHatNotFoundOnce, "failures", 1)
    resets = []
    backend = BuildHatBackend(reset=lambda: resets.append(1))
    await backend.start()
    assert resets == [1]
    assert backend.typeids()["A"] == 48
    await backend.close()


async def test_other_start_errors_are_not_retried(fake_buildhat, monkeypatch):
    def broken():
        raise RuntimeError("no serial port")
    monkeypatch.setattr(fake_buildhat, "Hat", broken)
    resets = []
    backend = BuildHatBackend(reset=lambda: resets.append(1))
    with pytest.raises(RuntimeError, match="no serial port"):
        await backend.start()
    assert resets == []


async def test_idle_sensor_stays_in_its_first_mode(fake_buildhat, monkeypatch):
    # the Color & Distance LED changes with the mode; cycling makes it flash
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    sensor = backend._devices["A"]
    sensor.calls.clear()
    for _ in range(4):
        values = await backend.read()
    assert set(sensor.calls) == {"color"}
    assert values["A"] == {"color": "red"}
    backend.set_program_running(True)
    for _ in range(3):
        values = await backend.read()
    assert sorted(set(sensor.calls)) == ["color", "distance", "reflection"]
    assert values["A"] == {"color": "red", "reflection": 40, "distance": 5}
    backend.set_program_running(False)
    sensor.calls.clear()
    for _ in range(3):
        values = await backend.read()
    assert set(sensor.calls) == {"color"}
    assert values["A"] == {"color": "red", "reflection": 40, "distance": 5}, "last values kept for blocks"
    await backend.close()


async def test_stop_all_then_running_ends_active(fake_buildhat, monkeypatch):
    # Run sends stop_all and then program.running; hatd handles them as concurrent tasks
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    backend = BuildHatBackend()
    await backend.start()
    backend.set_program_running(True)
    stop = asyncio.ensure_future(backend.stop_all())
    await asyncio.sleep(0)
    backend.set_program_running(True)
    await stop
    assert backend._active
    await backend.close()


async def test_hat_silent_while_a_device_attaches_is_reported(fake_buildhat, monkeypatch):
    # the first read of a newly attached device must not hang start() or a refresh forever
    monkeypatch.setattr("b3hatd.buildhat_backend.HAT_TIMEOUT", 0.3)
    monkeypatch.setattr(fake_buildhat, "ColorDistanceSensor", FakeHangingColorDistance)
    monkeypatch.setattr(FakeHangingColorDistance, "used", set())
    monkeypatch.setattr(FakeHat, "types", {"A": 37, "B": -1, "C": -1, "D": -1})
    FakeHangingColorDistance.hang = True
    backend = BuildHatBackend()
    try:
        with pytest.raises(B3Error) as e:
            await asyncio.wait_for(backend.start(), 3)
        assert e.value.code == "hat_not_responding"
    finally:
        FakeHangingColorDistance.hang = False
        await backend.close()


async def test_no_new_buildhat_calls_after_the_hat_went_silent(hat):
    with pytest.raises(B3Error):
        hat._unresponsive()
    with pytest.raises(B3Error) as e:
        await hat.motor_start("A", 20)
    assert e.value.code == "hat_not_responding"


async def test_go_to_holds_until_the_motor_stands_on_target_then_releases(hat, monkeypatch):
    # buildhat releases the motor 0.2 s after its ramp; a fast move then coasts up to 30 degrees past
    monkeypatch.setattr(FakeMotor, "lag", 5)
    await asyncio.wait_for(hat.motor_go_to("A", 270, "shortest", 75), 3)
    dev = hat._devices["A"]
    assert dev.release_seen is False, "held through the end of the ramp"
    assert dev.apos == -90 and dev._lag == 0, "waited until the motor reported the target"
    assert dev.release is True
    assert dev.log[-1] == ("coast",), "free to turn by hand afterwards"


async def test_go_to_gives_up_holding_after_the_settle_limit(hat, monkeypatch):
    monkeypatch.setattr(FakeMotor, "lag", 10 ** 6)  # never reaches the target
    monkeypatch.setattr("b3hatd.buildhat_backend.SETTLE_LIMIT", 0.3)
    await asyncio.wait_for(hat.motor_go_to("A", 90, "shortest", 75), 2)
    assert hat._devices["A"].log[-1] == ("coast",)


async def test_stop_while_settling_ends_at_once(hat, monkeypatch):
    monkeypatch.setattr(FakeMotor, "lag", 10 ** 6)
    task = asyncio.create_task(hat.motor_go_to("A", 90, "shortest", 75))
    await asyncio.sleep(0.3)  # the ramp takes 0.05 s; now it is holding and waiting
    await hat.motor_stop("A")
    with pytest.raises(B3Error) as e:
        await asyncio.wait_for(task, 1)
    assert e.value.code == "interrupted"
    for _ in range(10):
        if hat._inflight["A"].done():
            break
        await asyncio.sleep(0.05)
    assert hat._inflight["A"].done(), "the holding thread noticed the stop"


async def test_run_for_degrees_holds_until_the_motor_stands_on_target(hat, monkeypatch):
    monkeypatch.setattr(FakeMotor, "lag", 5)
    await asyncio.wait_for(hat.motor_run_for_degrees("A", 360, -75), 3)
    dev = hat._devices["A"]
    assert dev.release_seen is False
    assert dev.pos == -360 and dev._lag == 0, "waited until the motor reported the target"
    assert dev.release is True
    assert dev.log[-1] == ("coast",)

