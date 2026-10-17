import asyncio
import itertools

from b3hatd.ws import API_VERSION

_ids = itertools.count(1)
_buffers: dict[int, list] = {}


async def open_ws(client):
    ws = await client.ws_connect("/api/ws")
    _buffers[id(ws)] = []  # id() of a closed socket from an earlier test may be reused
    hello = await ws.receive_json(timeout=2)
    assert hello["type"] == "hello"
    await ws.send_json({"type": "hello", "api_version": API_VERSION})
    return ws, hello["client_id"]


async def _next(ws, pred, timeout):
    buf = _buffers.setdefault(id(ws), [])
    for i, msg in enumerate(buf):
        if pred(msg):
            return buf.pop(i)

    async def _find():
        while True:
            msg = await ws.receive_json()
            if pred(msg):
                return msg
            if msg["type"] != "telemetry":
                buf.append(msg)
    return await asyncio.wait_for(_find(), timeout)


async def next_of_type(ws, type_, timeout=2.0):
    return await _next(ws, lambda m: m["type"] == type_, timeout)


async def reply_for(ws, rid, timeout=2.0):
    return await _next(ws, lambda m: m["type"] == "reply" and m["id"] == rid, timeout)


async def call(ws, cmd, args=None, id=None, timeout=2.0):
    rid = id if id is not None else next(_ids)
    await ws.send_json({"id": rid, "cmd": cmd, "args": args or {}})
    return await reply_for(ws, rid, timeout)
