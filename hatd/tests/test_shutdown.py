"""hatd as a real process: SIGTERM with an editor connected must not hang."""

import asyncio
import signal
import socket
import sys
import time
from pathlib import Path

import aiohttp

HATD_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _login(session: aiohttp.ClientSession, base: str) -> None:
    for _ in range(100):
        try:
            resp = await session.post(f"{base}/api/login", json={"pin": "1234"})
            assert resp.status == 200
            return
        except aiohttp.ClientConnectionError:
            await asyncio.sleep(0.1)
    raise AssertionError("hatd did not start")


async def test_sigterm_with_open_websocket_exits_quickly(tmp_path):
    port = _free_port()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'pin = "1234"\n'
        f'data_dir = "{tmp_path}"\n'
        f'static_dir = "{tmp_path / "editor"}"\n'
        'http_host = "127.0.0.1"\n'
        f"http_port = {port}\n"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "b3hatd", "--config", str(cfg), "--sim", cwd=HATD_DIR,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
            await _login(session, base)
            ws = await session.ws_connect(f"{base}/api/ws")
            await ws.receive_json(timeout=2)  # hello
            started = time.monotonic()
            proc.send_signal(signal.SIGTERM)
            while True:  # telemetry keeps coming until hatd closes the socket
                msg = await ws.receive(timeout=5)
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
            assert await asyncio.wait_for(proc.wait(), 5) == 0
            assert time.monotonic() - started < 3
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
