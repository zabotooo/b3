"""Projects stored on the Pi as <id>.sb3 + <id>.json."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from .errors import B3Error
from .keys import CONFIG, STORE

_ID = re.compile(r"^[0-9a-f]{32}$")


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _paths(self, pid: str) -> tuple[Path, Path]:
        if not isinstance(pid, str) or not _ID.match(pid):
            raise B3Error("bad_args", "Invalid project id")
        return self.root / f"{pid}.sb3", self.root / f"{pid}.json"

    def list(self) -> list[dict]:
        items = []
        for meta_path in self.root.glob("*.json"):
            try:
                items.append(json.loads(meta_path.read_text()))
            except (OSError, ValueError):
                continue
        return sorted(items, key=lambda m: m["modified"], reverse=True)

    def get(self, pid: str) -> bytes:
        sb3, _ = self._paths(pid)
        if not sb3.exists():
            raise B3Error("not_found", "Project not found")
        return sb3.read_bytes()

    def put(self, pid: str, name: str, data: bytes) -> dict:
        sb3, meta_path = self._paths(pid)
        name = (name or "").strip()
        if not 1 <= len(name) <= 100:
            raise B3Error("bad_args", "Project name must be 1-100 characters")
        if not data.startswith(b"PK\x03\x04"):
            raise B3Error("bad_args", "Project must be an .sb3 (zip) file")
        meta = {
            "id": pid,
            "name": name,
            "modified": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
        _atomic_write(sb3, data)
        _atomic_write(meta_path, json.dumps(meta).encode())
        return meta

    def delete(self, pid: str) -> None:
        sb3, meta_path = self._paths(pid)
        if not sb3.exists():
            raise B3Error("not_found", "Project not found")
        sb3.unlink()
        meta_path.unlink(missing_ok=True)


async def _list(request: web.Request) -> web.Response:
    return web.json_response(request.app[STORE].list())


async def _get(request: web.Request) -> web.Response:
    data = request.app[STORE].get(request.match_info["pid"])
    return web.Response(body=data, content_type="application/zip")


async def _put(request: web.Request) -> web.Response:
    data = await request.read()
    meta = request.app[STORE].put(request.match_info["pid"], request.query.get("name", ""), data)
    return web.json_response(meta)


async def _delete(request: web.Request) -> web.Response:
    request.app[STORE].delete(request.match_info["pid"])
    return web.Response(status=204)


def setup(app: web.Application) -> None:
    app[STORE] = ProjectStore(app[CONFIG].data_dir / "projects")
    app.router.add_get("/api/projects", _list)
    app.router.add_get("/api/projects/{pid}", _get)
    app.router.add_put("/api/projects/{pid}", _put)
    app.router.add_delete("/api/projects/{pid}", _delete)
