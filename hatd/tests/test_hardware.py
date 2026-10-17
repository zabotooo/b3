"""Run on the Pi: B3_HW_MOTOR=B python3 -m pytest -m hardware tests/test_hardware.py -v

Needs an encoder motor on port $B3_HW_MOTOR (default B) that can turn freely.
"""

import asyncio
import gc
import os
import time

import pytest
import pytest_asyncio

from b3hatd.errors import B3Error

pytestmark = pytest.mark.hardware
MOTOR = os.environ.get("B3_HW_MOTOR", "B")


@pytest_asyncio.fixture
async def hat():
    from b3hatd.buildhat_backend import BuildHatBackend
    backend = BuildHatBackend()
    await backend.start()
    # The previous test's backend may still hold the port for a moment; hatd retries
    # opening on every refresh, so do the same here.
    ports = [p for p in (MOTOR, os.environ.get("B3_HW_ANGULAR"), os.environ.get("B3_HW_CDS")) if p]
    for _ in range(40):
        if all(backend.typeids()[p] is not None for p in ports):
            break
        gc.collect()
        await asyncio.sleep(0.05)
        await backend.read()
    yield backend
    await backend.stop_all()
    await backend.close()


async def test_detects_motor(hat):
    await hat.read()
    assert hat.typeids()[MOTOR] in (38, 46, 47, 48, 49, 65, 75, 76)


async def test_vin(hat):
    assert 5.0 < await hat.vin() < 12.0


async def test_run_for_degrees(hat):
    before = (await hat.read())[MOTOR]["position"]
    await hat.motor_run_for_degrees(MOTOR, 90, 30)
    after = (await hat.read())[MOTOR]["position"]
    assert 60 <= after - before <= 130  # overshoot is a known issue, see hardware-notes.md


async def test_negative_speed_turns_back(hat):
    before = (await hat.read())[MOTOR]["position"]
    await hat.motor_run_for_degrees(MOTOR, 90, -30)
    after = (await hat.read())[MOTOR]["position"]
    assert after < before


async def test_stop_interrupts_run_quickly(hat):
    task = asyncio.create_task(hat.motor_run_for_degrees(MOTOR, 3600, 20))
    await asyncio.sleep(0.5)
    t0 = time.monotonic()
    await hat.stop_all()
    with pytest.raises(B3Error) as e:
        await asyncio.wait_for(task, 2)
    assert e.value.code == "interrupted"
    assert time.monotonic() - t0 < 1.0


async def test_telemetry_step_is_fast_enough(hat):
    await hat.read()
    t0 = time.monotonic()
    for _ in range(20):
        await hat.read()
    per_read = (time.monotonic() - t0) / 20
    print(f"read() takes {per_read * 1000:.1f} ms")
    assert per_read < 0.05


async def test_empty_port_errors(hat):
    empty = [p for p, t in hat.typeids().items() if t is None]
    if not empty:
        pytest.skip("no empty port")
    with pytest.raises(B3Error) as e:
        await hat.motor_start(empty[0], 10)
    assert e.value.code == "no_device"


async def _interrupted_run(hat):
    task = asyncio.create_task(hat.motor_run_for_degrees(MOTOR, 3600, 20))
    await asyncio.sleep(0.3)
    await hat.motor_stop(MOTOR)
    with pytest.raises(B3Error):
        await asyncio.wait_for(task, 2)


async def test_repeated_interrupts_do_not_leak_threads(hat):
    # buildhat never resolves a ramp interrupted by coast; each one used to pin a worker thread
    for _ in range(10):
        await _interrupted_run(hat)
    await asyncio.wait_for(hat.read(), 2)
    await asyncio.wait_for(hat.motor_run_for_degrees(MOTOR, 90, 30), 5)


async def test_start_right_after_stop_keeps_running(hat):
    await _interrupted_run(hat)
    await hat.motor_start(MOTOR, 30)
    await asyncio.sleep(0.6)
    speed = (await hat.read())[MOTOR]["speed"]
    await hat.motor_stop(MOTOR)
    assert abs(speed) > 5


ANGULAR = os.environ.get("B3_HW_ANGULAR")    # port with an absolute-position motor
CDS = os.environ.get("B3_HW_CDS")            # port with a BOOST Color & Distance sensor


async def test_new_command_replaces_running_move(hat):
    task = asyncio.create_task(hat.motor_run_for_degrees(MOTOR, 3600, 20))
    await asyncio.sleep(0.5)
    t0 = time.monotonic()
    await hat.motor_start(MOTOR, 30)
    with pytest.raises(B3Error) as e:
        await asyncio.wait_for(task, 2)
    assert e.value.code == "interrupted"
    assert time.monotonic() - t0 < 1.0
    await asyncio.sleep(0.6)
    speed = (await hat.read())[MOTOR]["speed"]
    await hat.motor_stop(MOTOR)
    assert abs(speed) > 5


async def test_cancelled_moves_do_not_leak_threads(hat):
    # browser closed mid-move: the command task is cancelled, then stop_all runs
    import threading
    before = threading.active_count()
    for _ in range(10):
        task = asyncio.create_task(hat.motor_run_for_degrees(MOTOR, 3600, 20))
        await asyncio.sleep(0.3)
        task.cancel()
        await hat.stop_all()
    await asyncio.sleep(0.5)
    assert threading.active_count() <= before + 2
    await asyncio.wait_for(hat.motor_run_for_degrees(MOTOR, 90, 30), 5)


async def test_go_to_spike_position_270(hat):
    if not ANGULAR:
        pytest.skip("set B3_HW_ANGULAR")
    for _ in range(40):
        if hat.typeids()[ANGULAR] is not None:
            break
        await asyncio.sleep(0.05)
        await hat.read()
    await asyncio.wait_for(hat.motor_go_to(ANGULAR, 270, "shortest", 40), 5)
    await asyncio.sleep(0.3)
    apos = (await hat.read())[ANGULAR]["aposition"]
    print(f"go_to 270 -> aposition {apos}")
    assert abs(((apos + 90 + 180) % 360) - 180) <= 5  # held until it stands there (was ±31 before)


async def test_color_distance_sensor_values(hat):
    if not CDS:
        pytest.skip("set B3_HW_CDS")
    hat.set_program_running(True)  # idle reads only the color mode
    for _ in range(40):
        if hat.typeids()[CDS] is not None:
            break
        await asyncio.sleep(0.05)
        await hat.read()
    t0 = time.monotonic()
    values = (await hat.read())[CDS]
    print(f"C&D values {values}, read() with all ports {1000 * (time.monotonic() - t0):.1f} ms")
    for _ in range(20):  # the first read after program start fetches every mode in the background
        if set(values) == {"color", "reflection", "distance"}:
            break
        await asyncio.sleep(0.05)
        values = (await hat.read())[CDS]
    assert set(values) == {"color", "reflection", "distance"}
