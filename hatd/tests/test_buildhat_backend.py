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
from concurrent.futures import Future

import pytest
import pytest_asyncio

from b3hatd.buildhat_backend import BuildHatBackend
from b3hatd.errors import B3Error


class FakeInstance:
    def __init__(self):
        self.rampftr = [[] for _ in range(4)]
        self.pulseftr = [[] for _ in range(4)]
        self.cbqueue = queue.Queue()


class FakeHat:
    types = {"A": 48, "B": -1, "C": -1, "D": -1}

    def get(self):
        return {p: {"typeid": t} for p, t in self.types.items()}

    def get_vin(self):
        return 8.0


class FakeMotor:
    failures = 0
    instance: FakeInstance = None
    blocked = 0
    gets = 0
    lock = threading.Lock()

    def __init__(self, port):
        if FakeMotor.failures:
            FakeMotor.failures -= 1
            raise RuntimeError("Port already used")
        self.idx = "ABCD".index(port)
        self.speed = 0
        self.epoch = 0
        self.log = []

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
            time.sleep(0.1)  # buildhat: time.sleep(0.2); self.coast()
            self.coast()
        finally:
            with FakeMotor.lock:
                FakeMotor.blocked -= 1

    # buildhat Motor API ---------------------------------------------------
    def run_for_degrees(self, degrees, speed=None, blocking=True):
        self.log.append(("run_for_degrees", degrees, speed))
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
        return [self.speed, 0, 0]

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
    FakeMotor.failures = 0
    FakeMotor.instance = instance
    FakeMotor.blocked = 0
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
    first = asyncio.create_task(hat.motor_run_for_degrees("A", 3600, 10))
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
    assert sorted(sensor.calls) == ["color", "distance", "reflection"]  # filled once on attach
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
