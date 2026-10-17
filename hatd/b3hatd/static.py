"""Serves the editor build. Registered last: it is a catch-all GET route."""

from aiohttp import web

from .keys import CONFIG

NO_EDITOR_HTML = (
    "<!doctype html><title>B3</title>"
    "<p>B3 editor is not installed. hatd is running.</p>"
)


async def handler(request: web.Request) -> web.StreamResponse:
    root = request.app[CONFIG].static_dir.resolve()
    rel = request.match_info["tail"] or "index.html"
    path = (root / rel).resolve()
    if path.is_relative_to(root) and path.is_file():
        # editor bundles have fixed names (gui.js); revalidate so an update is picked up
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    if rel == "index.html":
        return web.Response(text=NO_EDITOR_HTML, content_type="text/html")
    raise web.HTTPNotFound()


def setup(app: web.Application) -> None:
    app.router.add_get("/{tail:.*}", handler)
