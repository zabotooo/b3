"""Simulates browsers: python3 -m b3hatd.loadcheck --url http://HOST:8080 --pin 1234 --clients 3 --seconds 60"""

import argparse
import asyncio
import time

import aiohttp

from .ws import API_VERSION


async def _client(session: aiohttp.ClientSession, base: str, seconds: float, controller: bool) -> float:
    count = 0
    async with session.ws_connect(f"{base}/api/ws") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "hello", "api_version": API_VERSION})
        if controller:
            await ws.send_json({"id": 1, "cmd": "control.claim", "args": {}})
        start = time.monotonic()
        end = start + seconds
        next_ping = start + 1
        rid = 2
        while (now := time.monotonic()) < end:
            if controller and now >= next_ping:
                await ws.send_json({"id": rid, "cmd": "ping", "args": {}})
                rid += 1
                next_ping += 1
            try:
                msg = await ws.receive_json(timeout=min(0.5, end - now))
            except asyncio.TimeoutError:
                continue
            if msg["type"] == "telemetry":
                count += 1
    return count / seconds


async def loadcheck(base: str, pin: str, clients: int, seconds: float) -> list[float]:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        async with session.post(f"{base}/api/login", json={"pin": pin}) as resp:
            resp.raise_for_status()
        return list(await asyncio.gather(
            *(_client(session, base, seconds, i == 0) for i in range(clients))))


def main() -> None:
    parser = argparse.ArgumentParser(prog="b3hatd.loadcheck")
    parser.add_argument("--url", required=True)
    parser.add_argument("--pin", required=True)
    parser.add_argument("--clients", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    rates = asyncio.run(loadcheck(args.url.rstrip("/"), args.pin, args.clients, args.seconds))
    for i, rate in enumerate(rates):
        print(f"client {i}: {rate:.1f} telemetry msg/s")


if __name__ == "__main__":
    main()
