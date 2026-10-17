import asyncio

import pytest

from b3hatd.control import ControlManager


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def env():
    clock = Clock()
    stops = []
    changes = []

    async def stop_everything():
        stops.append(True)

    mgr = ControlManager(stop_everything, on_change=changes.append, timeout=3.0, clock=clock)
    return mgr, clock, stops, changes


async def test_claim_and_takeover(env):
    mgr, _, _, changes = env
    assert mgr.holder is None
    await mgr.claim("a")
    assert mgr.is_controller("a")
    await mgr.claim("b")
    assert mgr.is_controller("b") and not mgr.is_controller("a")
    assert changes == ["a", "b"]


async def test_reclaim_by_holder_does_not_notify(env):
    mgr, _, _, changes = env
    await mgr.claim("a")
    await mgr.claim("a")
    assert changes == ["a"]


async def test_none_is_never_controller(env):
    mgr, *_ = env
    assert not mgr.is_controller(None)


async def test_timeout_stops_and_releases(env):
    mgr, clock, stops, changes = env
    await mgr.claim("a")
    clock.t = 2.0
    mgr.ping("a")
    clock.t = 4.9
    assert await mgr.check() is False
    clock.t = 5.1
    assert await mgr.check() is True
    assert mgr.holder is None
    assert stops == [True]
    assert changes == ["a", None]


async def test_ping_from_non_holder_is_ignored(env):
    mgr, clock, stops, _ = env
    await mgr.claim("a")
    clock.t = 2.5
    mgr.ping("b")
    clock.t = 3.5
    assert await mgr.check() is True


async def test_release_on_disconnect(env):
    mgr, _, stops, changes = env
    await mgr.claim("a")
    await mgr.release("b", stop=True)
    assert mgr.holder == "a" and stops == []
    await mgr.release("a", stop=True)
    assert mgr.holder is None and stops == [True]
    assert changes == ["a", None]


async def test_check_without_holder(env):
    mgr, clock, stops, _ = env
    clock.t = 100
    assert await mgr.check() is False
    assert stops == []


async def test_watchdog_survives_failing_stop():
    calls = []

    async def failing_stop():
        calls.append(1)
        raise RuntimeError("serial glitch")

    changes = []
    clock = Clock()
    mgr = ControlManager(failing_stop, on_change=changes.append, timeout=1.0, clock=clock)
    await mgr.claim("a")
    clock.t = 5
    task = asyncio.create_task(mgr.run(0.01))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    assert calls == [1]
    assert changes == ["a", None]  # others are told control is free even if stopping failed


async def test_takeover_stops_the_robot(env):
    mgr, _, stops, changes = env
    await mgr.claim("a")
    assert stops == []          # nobody held control before
    await mgr.claim("a")
    assert stops == []          # re-claim by the holder
    await mgr.claim("b")
    assert stops == [True]      # robot stopped when b took over from a
    assert changes == ["a", "b"]
