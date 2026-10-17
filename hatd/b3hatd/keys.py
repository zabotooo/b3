"""aiohttp application keys (AppKey on aiohttp >= 3.9, plain strings on 3.8)."""

from aiohttp import web


def _key(name: str):
    return web.AppKey(name) if hasattr(web, "AppKey") else name


CONFIG = _key("config")
BACKEND = _key("backend")
SOUND = _key("sound")
SESSIONS = _key("sessions")
STORE = _key("store")
CONTROL = _key("control")
CLIENTS = _key("clients")
TASKS = _key("tasks")
EXIT_CODE = _key("exit_code")
