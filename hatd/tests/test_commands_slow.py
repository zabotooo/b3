import asyncio

import pytest
import pytest_asyncio

from b3hatd.sim import SimBackend
from tests.helpers import call, open_ws, reply_for


@pytest.fixture
def backend():
    return SimBackend(max_dps=10)  # 90 degrees at 100 % = 9 s


@pytest_asyncio.fixture
async def ctl(authed):
    ws, _ = await open_ws(authed)
    assert (await call(ws, "control.claim"))["ok"]
    yield ws
    await ws.close()


async def _start_long_run(ws, rid):
    await ws.send_json({"id": rid, "cmd": "motor.run_for",
                        "args": {"port": "A", "unit": "degrees", "value": 90, "speed": 100}})
    await asyncio.sleep(0.05)


async def test_stop_all_interrupts_pending_run(ctl, backend):
    backend.attach("A", 48)
    await _start_long_run(ctl, 900)
    assert (await call(ctl, "stop_all"))["ok"]
    assert (await reply_for(ctl, 900))["error"]["code"] == "interrupted"


async def test_two_stacks_run_concurrently(ctl, backend):
    backend.attach("A", 48)
    backend.attach("B", 48)
    await _start_long_run(ctl, 901)
    assert (await call(ctl, "motor.start", {"port": "B", "speed": 20}))["ok"]


async def test_device_unplugged_mid_run(ctl, backend):
    backend.attach("A", 48)
    await _start_long_run(ctl, 902)
    backend.detach("A")
    assert (await reply_for(ctl, 902))["ok"] is False
    reply = await call(ctl, "motor.start", {"port": "A", "speed": 10})
    assert reply["error"]["code"] == "no_device"
