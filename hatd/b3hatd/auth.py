"""PIN login and session cookies."""

import asyncio
import secrets

from aiohttp import web

from .errors import B3Error
from .keys import CONFIG, SESSIONS

COOKIE = "b3session"


class Sessions:
    def __init__(self):
        self._tokens: set[str] = set()

    def create(self) -> str:
        token = secrets.token_hex(16)
        self._tokens.add(token)
        return token

    def valid(self, token: str | None) -> bool:
        return token is not None and token in self._tokens


@web.middleware
async def middleware(request: web.Request, handler):
    path = request.path
    if path.startswith("/api/") and path != "/api/login":
        if not request.app[SESSIONS].valid(request.cookies.get(COOKIE)):
            raise B3Error("unauthorized", "PIN required")
    return await handler(request)


async def login(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        raise B3Error("bad_args", "JSON body required")
    pin = body.get("pin") if isinstance(body, dict) else None
    if not isinstance(pin, str) or not secrets.compare_digest(pin, request.app[CONFIG].pin):
        # no lockout (spec), but slow down guessing a short PIN over the network
        await asyncio.sleep(request.app[CONFIG].login_failure_delay)
        raise B3Error("unauthorized", "Wrong PIN")
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, request.app[SESSIONS].create(), httponly=True, samesite="Strict")
    return resp
