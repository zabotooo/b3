import asyncio


class FakeProcess:
    def __init__(self):
        self.killed = False
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        return 0

    def kill(self) -> None:
        self.killed = True
        self._done.set()

    def finish(self) -> None:
        self._done.set()


class FakeRunner:
    """Records commands instead of starting aplay/amixer."""

    def __init__(self):
        self.spawned: list[tuple[list[str], FakeProcess]] = []
        self.ran: list[list[str]] = []

    async def spawn(self, args: list[str]) -> FakeProcess:
        proc = FakeProcess()
        self.spawned.append((args, proc))
        return proc

    async def run(self, args: list[str]) -> int:
        self.ran.append(args)
        return 0
