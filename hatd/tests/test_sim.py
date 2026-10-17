import asyncio

import pytest

from b3hatd.errors import B3Error
from b3hatd.sim import SimBackend


@pytest.fixture
def sim():
    return SimBackend(max_dps=100_000)


async def test_attach_and_read(sim):
    sim.attach("A", 48)
    sim.attach("B", 61, color="red")
    assert sim.typeids() == {"A": 48, "B": 61, "C": None, "D": None}
    values = await sim.read()
    assert values["A"] == {"position": 0, "aposition": 0, "speed": 0}
    assert values["B"] == {"color": "red", "reflection": 0}
    assert "C" not in values


async def test_detach(sim):
    sim.attach("A", 48)
    sim.detach("A")
    assert sim.typeids()["A"] is None
    assert "A" not in await sim.read()


async def test_run_for_degrees_moves(sim):
    sim.attach("A", 48)
    await sim.motor_run_for_degrees("A", 90, 50)
    assert sim.values["A"]["position"] == 90
    assert sim.values["A"]["aposition"] == 90
    await sim.motor_run_for_degrees("A", 180, -50)
    assert sim.values["A"]["position"] == -90
    assert sim.values["A"]["aposition"] == -90
    assert ("run_for_degrees", "A", 90, 50) in sim.calls


async def test_run_for_empty_port_fails(sim):
    with pytest.raises(B3Error) as e:
        await sim.motor_run_for_degrees("C", 90, 50)
    assert e.value.code == "no_device"


async def test_stop_interrupts_run(sim):
    slow = SimBackend(max_dps=10)  # 90 degrees at 100% = 9 s
    slow.attach("A", 48)
    task = asyncio.create_task(slow.motor_run_for_degrees("A", 90, 100))
    await asyncio.sleep(0.05)
    await slow.motor_stop("A")
    with pytest.raises(B3Error) as e:
        await asyncio.wait_for(task, 1)
    assert e.value.code == "interrupted"
    assert slow.values["A"]["speed"] == 0


async def test_stop_all_interrupts_every_port():
    slow = SimBackend(max_dps=10)
    slow.attach("A", 48)
    slow.attach("B", 2)
    t1 = asyncio.create_task(slow.motor_run_for_degrees("A", 90, 100))
    t2 = asyncio.create_task(slow.motor_run_for_seconds("B", 10, 100))
    await asyncio.sleep(0.05)
    await slow.stop_all()
    for t in (t1, t2):
        with pytest.raises(B3Error):
            await asyncio.wait_for(t, 1)
    assert slow.values["B"]["power"] == 0


async def test_passive_motor_start_sets_power(sim):
    sim.attach("B", 2)
    await sim.motor_start("B", -40)
    assert sim.values["B"]["power"] == -40


async def test_go_to_shortest_and_directions(sim):
    sim.attach("A", 48, aposition=170)
    await sim.motor_go_to("A", -170, "shortest", 50)   # +20 across 180
    assert sim.values["A"]["aposition"] == -170
    assert sim.values["A"]["position"] == 20
    await sim.motor_go_to("A", -150, "ccw", 50)        # ccw from -170 to -150 = -340
    assert sim.values["A"]["position"] == -320
    await sim.motor_go_to("A", -150, "cw", 50)         # already there
    assert sim.values["A"]["position"] == -320


async def test_lights_and_matrix(sim):
    sim.attach("A", 8)
    sim.attach("B", 64)
    sim.attach("C", 62)
    await sim.light_set("A", 70)
    await sim.matrix_set("B", [("red", 10)] * 9)
    await sim.sensor_lights("C", [100, 0, 100, 0])
    assert sim.values["A"]["brightness"] == 70
    assert ("matrix_set", "B", [("red", 10)] * 9) in sim.calls
    assert ("sensor_lights", "C", [100, 0, 100, 0]) in sim.calls


async def test_vin(sim):
    sim.set_vin(6.5)
    assert await sim.vin() == 6.5
