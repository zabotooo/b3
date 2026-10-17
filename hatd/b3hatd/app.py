"""Builds the aiohttp application."""

import asyncio
import logging
import os
import signal

from aiohttp import web

from . import auth, projects, static, ws
from . import sound as sound_routes
from .backend import HatBackend
from .clients import Clients
from .config import Config
from .control import ControlManager
from .errors import B3Error
from .keys import BACKEND, CLIENTS, CONFIG, CONTROL, EXIT_CODE, SESSIONS, SOUND, TASKS
from .telemetry import TelemetryLoop

log = logging.getLogger(__name__)

STATUS = {
    "bad_args": 400,
    "unauthorized": 401,
    "not_found": 404,
}


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except B3Error as e:
        return web.json_response({"error": e.to_dict()}, status=STATUS.get(e.code, 400))


async def _stop_everything(app: web.Application) -> None:
    try:
        await app[BACKEND].stop_all()
    except Exception:
        log.exception("stop_all failed")
    if app[SOUND] is not None:
        await app[SOUND].stop()


async def fatal(app: web.Application, error: B3Error) -> None:
    """The hardware is gone: tell the editors, then stop so systemd restarts hatd."""
    if app[EXIT_CODE]["code"]:
        return
    log.error("stopping: %s", error.message)
    app[EXIT_CODE]["code"] = 75
    await app[CLIENTS].broadcast({"type": "error", "error": error.to_dict()})
    os.kill(os.getpid(), signal.SIGTERM)


async def _notify_control(app: web.Application, holder: str | None) -> None:
    clients = app[CLIENTS]
    for cid in clients.ids():
        await clients.send(cid, {"type": "control", "holder": holder, "you": cid == holder})


async def _on_startup(app: web.Application) -> None:
    await app[BACKEND].start()
    config = app[CONFIG]
    telemetry = TelemetryLoop(app[BACKEND], app[CLIENTS].broadcast, interval=config.telemetry_interval,
                              on_fatal=lambda e: fatal(app, e))
    app[TASKS] = [
        asyncio.ensure_future(app[CONTROL].run(config.control_timeout / 6)),
        asyncio.ensure_future(telemetry.run()),
    ]


async def _on_shutdown(app: web.Application) -> None:
    # aiohttp waits for open WebSocket handlers before cleanup; end them first
    await app[CLIENTS].close_all()


async def _on_cleanup(app: web.Application) -> None:
    for task in app[TASKS]:
        task.cancel()
    await asyncio.gather(*app[TASKS], return_exceptions=True)
    await _stop_everything(app)
    await app[BACKEND].close()


def create_app(config: Config, backend: HatBackend, sound) -> web.Application:
    app = web.Application(
        middlewares=[error_middleware, auth.middleware],
        client_max_size=50 * 1024 * 1024,
    )
    app[CONFIG] = config
    app[BACKEND] = backend
    app[SOUND] = sound
    app[SESSIONS] = auth.Sessions()
    app[CLIENTS] = Clients()
    app[EXIT_CODE] = {"code": 0}  # set by fatal(); the app is frozen once running
    pending: set[asyncio.Task] = set()

    def on_change(holder: str | None) -> None:
        task = asyncio.ensure_future(_notify_control(app, holder))
        pending.add(task)
        task.add_done_callback(pending.discard)

    app[CONTROL] = ControlManager(lambda: _stop_everything(app), on_change=on_change,
                                  timeout=config.control_timeout)
    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)
    app.on_cleanup.append(_on_cleanup)

    app.router.add_post("/api/login", auth.login)
    projects.setup(app)
    sound_routes.setup(app)
    ws.setup(app)
    static.setup(app)  # must stay last
    return app
