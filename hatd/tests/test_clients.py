import asyncio

from b3hatd.clients import Clients


class FakeWS:
    def __init__(self, hang=False):
        self.hang = hang
        self.closed = False
        self.sent = []

    async def send_json(self, msg):
        if self.hang:
            await asyncio.sleep(3600)
        self.sent.append(msg)

    async def close(self):
        self.closed = True


async def test_stalled_client_does_not_block_others():
    clients = Clients(send_timeout=0.1)
    stuck, ok = FakeWS(hang=True), FakeWS()
    clients.add("stuck", stuck)
    clients.add("ok", ok)
    await asyncio.wait_for(clients.broadcast({"type": "telemetry"}), 1)
    assert ok.sent == [{"type": "telemetry"}]
    assert "stuck" not in clients.ids()
    await asyncio.sleep(0)
    assert stuck.closed
