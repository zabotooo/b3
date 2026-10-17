import asyncio

from b3hatd.sim import SimBackend
from b3hatd.telemetry import TelemetryLoop
from tests.helpers import next_of_type, open_ws


class Sink:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(msg)

    def of(self, type_):
        return [m for m in self.msgs if m["type"] == type_]


async def test_first_step_reports_devices_and_values():
    sim = SimBackend()
    sim.attach("A", 48, position=10)
    sink = Sink()
    loop = TelemetryLoop(sim, sink)
    await loop.step()
    assert sink.of("device") == [
        {"type": "device", "port": "A", "typeid": 48, "name": "Medium Angular Motor (Cyan)", "kind": "motor_abs"}]
    tele = sink.of("telemetry")[0]
    assert tele["vin"] == 8.0
    assert tele["ports"]["A"] == {"typeid": 48, "name": "Medium Angular Motor (Cyan)", "kind": "motor_abs",
                                  "position": 10, "aposition": 0, "speed": 0}
    assert tele["ports"]["B"] is None


async def test_device_change_reported_once():
    sim = SimBackend()
    sink = Sink()
    loop = TelemetryLoop(sim, sink)
    await loop.step()
    assert sink.of("device") == []
    sim.attach("C", 61)
    await loop.step()
    await loop.step()
    assert len(sink.of("device")) == 1
    sim.detach("C")
    await loop.step()
    assert sink.of("device")[-1] == {"type": "device", "port": "C", "typeid": None, "name": None, "kind": None}


async def test_unknown_device_reported():
    sim = SimBackend()
    sim.attach("D", 999)
    sink = Sink()
    await TelemetryLoop(sim, sink).step()
    assert sink.of("device")[0]["name"] == "Unknown device 999"
    assert sink.of("telemetry")[0]["ports"]["D"]["kind"] is None


async def test_read_failure_does_not_kill_loop():
    class Broken(SimBackend):
        fail = True

        async def read(self):
            if self.fail:
                self.fail = False
                raise RuntimeError("serial glitch")
            return await super().read()

    sim = Broken()
    sink = Sink()
    loop = TelemetryLoop(sim, sink)
    await loop.step()
    await loop.step()
    assert len(sink.of("telemetry")) == 1


async def test_vin_read_rarely():
    calls = []

    class Counting(SimBackend):
        async def vin(self):
            calls.append(1)
            return 7.5

    sink = Sink()
    loop = TelemetryLoop(Counting(), sink, vin_every=5)
    for _ in range(10):
        await loop.step()
    assert len(calls) == 2
    assert sink.of("telemetry")[-1]["vin"] == 7.5


async def test_clients_receive_telemetry(authed, backend):
    backend.attach("B", 62, distance_mm=120)
    ws, _ = await open_ws(authed)
    tele = await next_of_type(ws, "telemetry")
    assert tele["ports"]["B"]["distance_mm"] == 120
    await ws.close()


async def test_run_survives_broadcast_failure():
    sim = SimBackend()
    sent = []

    async def flaky(msg):
        if not sent:
            sent.append("boom")
            raise TypeError("not serialisable")
        sent.append(msg)

    task = asyncio.create_task(TelemetryLoop(sim, flaky, interval=0.01).run())
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    assert len(sent) > 2


async def test_rate_holds_when_reads_are_slow():
    class Slow(SimBackend):
        async def read(self):
            await asyncio.sleep(0.03)
            return await super().read()

    sink = Sink()
    task = asyncio.create_task(TelemetryLoop(Slow(), sink, interval=0.05).run())
    await asyncio.sleep(1.0)
    task.cancel()
    assert len(sink.of("telemetry")) >= 18  # 20 Hz despite 30 ms reads
