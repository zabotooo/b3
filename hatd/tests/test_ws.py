import asyncio

import b3hatd

from tests.helpers import call, next_of_type, open_ws, reply_for


async def test_ws_requires_login(client):
    resp = await client.get("/api/ws")
    assert resp.status == 401


async def test_hello(authed):
    ws = await authed.ws_connect("/api/ws")
    hello = await ws.receive_json()
    assert hello["api_version"] == "1"
    assert hello["version"] == b3hatd.__version__
    assert hello["control"] == {"holder": None}
    assert len(hello["client_id"]) == 32
    await ws.close()


async def test_wrong_api_version_closes(authed):
    ws = await authed.ws_connect("/api/ws")
    await ws.receive_json()
    await ws.send_json({"type": "hello", "api_version": "2"})
    msg = await next_of_type(ws, "error")
    assert msg["error"]["code"] == "bad_api_version"
    await asyncio.wait_for(ws.receive(), 2)
    assert ws.closed


async def test_commands_before_hello_rejected(authed):
    ws = await authed.ws_connect("/api/ws")
    await ws.receive_json()
    await ws.send_json({"id": 1, "cmd": "ping", "args": {}})
    msg = await next_of_type(ws, "error")
    assert msg["error"]["code"] == "bad_message"
    await ws.close()


async def test_garbage_does_not_close_connection(authed):
    ws, _ = await open_ws(authed)
    await ws.send_str("{not json")
    assert (await next_of_type(ws, "error"))["error"]["code"] == "bad_message"
    await ws.send_json([1, 2, 3])
    assert (await next_of_type(ws, "error"))["error"]["code"] == "bad_message"
    reply = await call(ws, "nope")
    assert reply["ok"] is False and reply["error"]["code"] == "unknown_cmd"
    await ws.send_json({"id": 5, "cmd": "ping", "args": [1]})
    reply = await reply_for(ws, 5)
    assert reply["error"]["code"] == "bad_args"
    assert (await call(ws, "ping"))["ok"] is True
    await ws.close()


async def test_claim_notifies_everyone(authed):
    ws1, id1 = await open_ws(authed)
    ws2, id2 = await open_ws(authed)
    reply = await call(ws1, "control.claim")
    assert reply == {"type": "reply", "id": reply["id"], "ok": True, "result": {"holder": id1}}
    m1 = await next_of_type(ws1, "control")
    m2 = await next_of_type(ws2, "control")
    assert m1 == {"type": "control", "holder": id1, "you": True}
    assert m2 == {"type": "control", "holder": id1, "you": False}
    await ws1.close()
    await ws2.close()


async def test_controller_disconnect_stops_and_releases(authed, backend):
    backend.attach("A", 48)
    ws1, _ = await open_ws(authed)
    ws2, id2 = await open_ws(authed)
    await call(ws1, "control.claim")
    await ws1.close()
    msg = await next_of_type(ws2, "control")
    while msg["holder"] is not None:
        msg = await next_of_type(ws2, "control")
    assert ("stop_all",) in backend.calls
    assert (await call(ws2, "control.claim"))["result"] == {"holder": id2}
    await ws2.close()


async def test_missing_ping_releases_control(authed, backend):
    # control_timeout is 0.3 s in the test config
    ws, _ = await open_ws(authed)
    await call(ws, "control.claim")
    await next_of_type(ws, "control")
    msg = await next_of_type(ws, "control", timeout=3)
    assert msg["holder"] is None
    assert ("stop_all",) in backend.calls
    await ws.close()


async def test_ping_keeps_control(authed):
    ws, cid = await open_ws(authed)
    await call(ws, "control.claim")
    for _ in range(8):
        await asyncio.sleep(0.1)
        await call(ws, "ping")
    reply = await call(ws, "control.claim")
    assert reply["result"]["holder"] == cid
    await ws.close()
