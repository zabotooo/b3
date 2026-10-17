import signal

from b3hatd import app as app_module
from b3hatd.errors import B3Error
from b3hatd.keys import EXIT_CODE
from tests.helpers import next_of_type, open_ws


async def test_fatal_tells_editors_and_stops_with_exit_code(authed, monkeypatch):
    kills = []
    monkeypatch.setattr(app_module.os, "kill", lambda pid, sig: kills.append(sig))
    ws, _ = await open_ws(authed)
    app = authed.server.app
    await app_module.fatal(app, B3Error("hat_not_responding", "Build HAT is not responding."))
    msg = await next_of_type(ws, "error")
    assert msg["error"]["code"] == "hat_not_responding"
    assert app[EXIT_CODE]["code"] == 75
    assert kills == [signal.SIGTERM]
    await app_module.fatal(app, B3Error("hat_not_responding", "again"))
    assert kills == [signal.SIGTERM], "only once"
    await ws.close()
