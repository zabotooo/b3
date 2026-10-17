import pytest
import pytest_asyncio

from tests.helpers import call, open_ws, reply_for


@pytest_asyncio.fixture
async def ctl(authed):
    """WebSocket that holds control."""
    ws, _ = await open_ws(authed)
    assert (await call(ws, "control.claim"))["ok"]
    yield ws
    await ws.close()


async def test_actuating_command_needs_control(authed, backend):
    backend.attach("A", 48)
    ws, _ = await open_ws(authed)
    reply = await call(ws, "motor.stop", {"port": "A"})
    assert reply["error"]["code"] == "not_controller"
    await ws.close()


async def test_run_for_degrees(ctl, backend):
    backend.attach("A", 48)
    reply = await call(ctl, "motor.run_for", {"port": "A", "unit": "degrees", "value": 90, "speed": 50})
    assert reply["ok"], reply
    assert backend.values["A"]["position"] == 90


async def test_run_for_seconds_passive(ctl, backend):
    backend.attach("B", 2)
    reply = await call(ctl, "motor.run_for", {"port": "B", "unit": "seconds", "value": 0.01, "speed": -30})
    assert reply["ok"], reply
    assert ("run_for_seconds", "B", 0.01, -30) in backend.calls


async def test_passive_motor_rejects_degrees(ctl, backend):
    backend.attach("B", 2)
    reply = await call(ctl, "motor.run_for", {"port": "B", "unit": "degrees", "value": 90, "speed": 50})
    assert reply["error"] == {"code": "wrong_device", "port": "B",
                              "message": "Port B: expected motor with encoder, found Train Motor"}


async def test_go_to_needs_absolute_motor(ctl, backend):
    backend.attach("A", 47)
    reply = await call(ctl, "motor.go_to", {"port": "A", "position": 0, "direction": "shortest", "speed": 50})
    assert reply["error"]["code"] == "wrong_device"


async def test_go_to(ctl, backend):
    backend.attach("A", 48)
    reply = await call(ctl, "motor.go_to", {"port": "A", "position": 90, "direction": "cw", "speed": 50})
    assert reply["ok"], reply
    assert backend.values["A"]["aposition"] == 90


async def test_empty_port(ctl):
    reply = await call(ctl, "motor.start", {"port": "C", "speed": 50})
    assert reply["error"]["code"] == "no_device"
    assert reply["error"]["port"] == "C"


@pytest.mark.parametrize("args", [
    {"port": "E", "speed": 50},
    {"port": "A", "speed": 500},
    {"port": "A", "speed": True},
    {"port": "A", "speed": 10.5},
    {"port": "A", "speed": "fast"},
    {"port": "A"},
])
async def test_bad_args(ctl, backend, args):
    backend.attach("A", 48)
    reply = await call(ctl, "motor.start", args)
    assert reply["error"]["code"] == "bad_args"


async def test_nan_is_rejected(ctl, backend):
    backend.attach("A", 48)
    await ctl.send_str('{"id": 77, "cmd": "motor.start", "args": {"port": "A", "speed": NaN}}')
    reply = await reply_for(ctl, 77)
    assert reply["error"]["code"] == "bad_args"


async def test_zero_speed_run_for_rejected(ctl, backend):
    backend.attach("A", 48)
    reply = await call(ctl, "motor.run_for", {"port": "A", "unit": "degrees", "value": 90, "speed": 0})
    assert reply["error"]["code"] == "bad_args"


async def test_pair_run_for(ctl, backend):
    backend.attach("A", 48)
    backend.attach("B", 48)
    reply = await call(ctl, "pair.run_for", {
        "left": "A", "right": "B", "unit": "degrees",
        "left_value": 360, "right_value": 180, "left_speed": -50, "right_speed": 25})
    assert reply["ok"], reply
    assert backend.values["A"]["position"] == -360
    assert backend.values["B"]["position"] == 180


async def test_pair_skips_stopped_wheel(ctl, backend):
    backend.attach("A", 48)
    backend.attach("B", 48)
    reply = await call(ctl, "pair.run_for", {
        "left": "A", "right": "B", "unit": "degrees",
        "left_value": 0, "right_value": 90, "left_speed": 0, "right_speed": 50})
    assert reply["ok"], reply
    assert backend.values["A"]["position"] == 0


async def test_pair_same_port_rejected(ctl, backend):
    backend.attach("A", 48)
    reply = await call(ctl, "pair.start", {"left": "A", "right": "A", "left_speed": 1, "right_speed": 1})
    assert reply["error"]["code"] == "bad_args"


async def test_pair_start_stop(ctl, backend):
    backend.attach("A", 48)
    backend.attach("B", 48)
    assert (await call(ctl, "pair.start", {"left": "A", "right": "B", "left_speed": -50, "right_speed": 50}))["ok"]
    assert backend.values["A"]["speed"] == -50
    assert (await call(ctl, "pair.stop", {"left": "A", "right": "B"}))["ok"]
    assert backend.values["B"]["speed"] == 0


async def test_lights(ctl, backend):
    backend.attach("A", 8)
    backend.attach("B", 64)
    backend.attach("C", 62)
    assert (await call(ctl, "light.set", {"port": "A", "brightness": 60}))["ok"]
    pixels = [["red", 10]] * 9
    assert (await call(ctl, "matrix.set", {"port": "B", "pixels": pixels}))["ok"]
    assert ("matrix_set", "B", [("red", 10)] * 9) in backend.calls
    assert (await call(ctl, "sensor.lights", {"port": "C", "values": [100, 50, 0, 100]}))["ok"]


@pytest.mark.parametrize("pixels", [
    [["red", 10]] * 8,
    [["purple", 10]] * 9,
    [["red", 11]] * 9,
    "red",
])
async def test_matrix_bad_pixels(ctl, backend, pixels):
    backend.attach("B", 64)
    reply = await call(ctl, "matrix.set", {"port": "B", "pixels": pixels})
    assert reply["error"]["code"] == "bad_args"


async def test_sensor_lights_wrong_device(ctl, backend):
    backend.attach("C", 61)
    reply = await call(ctl, "sensor.lights", {"port": "C", "values": [1, 2, 3, 4]})
    assert reply["error"]["code"] == "wrong_device"


async def test_sound_commands(ctl, sound, runner):
    reply = await call(ctl, "sound.play", {"md5": "0" * 32, "wait": False})
    assert reply["error"]["code"] == "not_found"
    reply = await call(ctl, "sound.beep", {"note": 60, "duration": None})
    assert reply["ok"], reply
    assert runner.spawned
    assert (await call(ctl, "sound.stop"))["ok"]
    assert runner.spawned[0][1].killed
    assert (await call(ctl, "sound.volume", {"value": 30}))["ok"]
    assert sound.volume == 30


async def test_stop_all_stops_sound(ctl, runner):
    await call(ctl, "sound.beep", {"note": 60, "duration": None})
    assert (await call(ctl, "stop_all"))["ok"]
    assert runner.spawned[0][1].killed


async def test_run_for_zero_returns_at_once(ctl, backend):
    backend.attach("A", 48)
    reply = await call(ctl, "motor.run_for", {"port": "A", "unit": "degrees", "value": 0, "speed": 50})
    assert reply["ok"], reply
    assert not [c for c in backend.calls if c[0] == "run_for_degrees"]
