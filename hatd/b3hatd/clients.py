"""Connected WebSocket clients."""

import asyncio
import logging

from aiohttp import WSCloseCode, web

log = logging.getLogger(__name__)


class Clients:
    def __init__(self, send_timeout: float = 1.0):
        self._ws: dict[str, web.WebSocketResponse] = {}
        self.send_timeout = send_timeout
        self._closing: set[asyncio.Task] = set()

    def add(self, cid: str, ws: web.WebSocketResponse) -> None:
        self._ws[cid] = ws

    def remove(self, cid: str) -> None:
        self._ws.pop(cid, None)

    def ids(self) -> list[str]:
        return list(self._ws)

    async def send(self, cid: str, msg: dict) -> None:
        ws = self._ws.get(cid)
        if ws is None or ws.closed:
            return
        try:
            await asyncio.wait_for(ws.send_json(msg), self.send_timeout)
        except asyncio.TimeoutError:
            # a half-dead connection (e.g. tablet left Wi-Fi) must not stall everyone else
            log.warning("client %s stalled, disconnecting", cid)
            self.remove(cid)
            task = asyncio.ensure_future(ws.close())
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)
        except (ConnectionResetError, RuntimeError):
            pass

    async def broadcast(self, msg: dict) -> None:
        for cid in self.ids():
            await self.send(cid, msg)

    async def close_all(self) -> None:
        """Close every connection (hatd is stopping); editors reconnect by themselves."""
        sockets = list(self._ws.values())
        self._ws.clear()
        await asyncio.gather(*(ws.close(code=WSCloseCode.GOING_AWAY, message=b"hatd stopping")
                               for ws in sockets), return_exceptions=True)
