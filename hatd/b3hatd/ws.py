"""WebSocket endpoint /api/ws."""

import asyncio
import json
import logging
import uuid

from aiohttp import WSMsgType, web

from . import __version__, commands
from .errors import B3Error
from .keys import CLIENTS, CONTROL

log = logging.getLogger(__name__)

API_VERSION = "1"


def _error(code: str, message: str) -> dict:
    return {"type": "error", "error": {"code": code, "message": message}}


async def _handle(app: web.Application, cid: str, data: dict) -> None:
    rid = data.get("id")
    try:
        cmd = data.get("cmd")
        args = data.get("args", {})
        if not isinstance(cmd, str):
            raise B3Error("bad_message", "Missing cmd")
        if not isinstance(args, dict):
            raise B3Error("bad_args", "args must be an object")
        result = await commands.dispatch(commands.Context(app, cid), cmd, args)
        reply = {"type": "reply", "id": rid, "ok": True, "result": result}
    except B3Error as e:
        reply = {"type": "reply", "id": rid, "ok": False, "error": e.to_dict()}
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("command failed: %r", data)
        reply = {"type": "reply", "id": rid, "ok": False,
                 "error": {"code": "internal", "message": "Internal error"}}
    await app[CLIENTS].send(cid, reply)


async def handler(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(request)
    cid = uuid.uuid4().hex
    clients = app[CLIENTS]
    control = app[CONTROL]
    clients.add(cid, ws)
    await clients.send(cid, {"type": "hello", "api_version": API_VERSION, "version": __version__,
                             "client_id": cid, "control": {"holder": control.holder}})
    greeted = False
    tasks: set[asyncio.Task] = set()
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                await clients.send(cid, _error("bad_message", "Invalid JSON"))
                continue
            if not isinstance(data, dict):
                await clients.send(cid, _error("bad_message", "Message must be an object"))
                continue
            if data.get("type") == "hello":
                if str(data.get("api_version", "")).split(".")[0] != API_VERSION:
                    await clients.send(cid, _error("bad_api_version",
                                                   f"hatd speaks API {API_VERSION}"))
                    await ws.close()
                    break
                greeted = True
                continue
            if not greeted:
                await clients.send(cid, _error("bad_message", "Send hello first"))
                continue
            task = asyncio.ensure_future(_handle(app, cid, data))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        clients.remove(cid)
        for task in tasks:
            task.cancel()
        # aiohttp 3.8 cancels the handler when the peer goes away; finish the stop anyway
        await asyncio.shield(control.release(cid, stop=True))
    return ws


def setup(app: web.Application) -> None:
    app.router.add_get("/api/ws", handler)
