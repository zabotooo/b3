from b3hatd.config import load_config


async def test_api_requires_login(client):
    resp = await client.get("/api/anything")
    assert resp.status == 401
    body = await resp.json()
    assert body["error"]["code"] == "unauthorized"


async def test_wrong_pin(client):
    resp = await client.post("/api/login", json={"pin": "0000"})
    assert resp.status == 401
    assert (await resp.json())["error"]["message"] == "Wrong PIN"


async def test_wrong_pin_has_no_lockout(client):
    for _ in range(10):
        await client.post("/api/login", json={"pin": "0000"})
    resp = await client.post("/api/login", json={"pin": "1234"})
    assert resp.status == 200


async def test_login_body_must_be_json(client):
    resp = await client.post("/api/login", data=b"pin=1234")
    assert resp.status == 400


async def test_login_sets_cookie_and_unlocks_api(client):
    resp = await client.post("/api/login", json={"pin": "1234"})
    assert resp.status == 200
    assert "b3session" in resp.cookies
    resp = await client.get("/api/anything")
    assert resp.status == 404


async def test_static_fallback_page_without_editor(client):
    resp = await client.get("/")
    assert resp.status == 200
    assert "B3 editor is not installed" in await resp.text()


async def test_static_serves_editor(client, config):
    config.static_dir.mkdir(parents=True)
    (config.static_dir / "index.html").write_text("<h1>editor</h1>")
    (config.static_dir / "app.js").write_text("console.log(1)")
    assert "editor" in await (await client.get("/")).text()
    assert (await client.get("/app.js")).status == 200
    assert (await client.get("/missing.js")).status == 404


async def test_editor_files_are_revalidated(client, config):
    # gui.js has no content hash in its name; after an update the browser must not reuse it
    config.static_dir.mkdir(parents=True)
    (config.static_dir / "index.html").write_text("<h1>editor</h1>")
    (config.static_dir / "gui.js").write_text("1")
    for path in ("/", "/gui.js"):
        resp = await client.get(path)
        assert resp.status == 200
        assert resp.headers["Cache-Control"] == "no-cache"


async def test_static_blocks_path_traversal(client, config, tmp_path):
    config.static_dir.mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("secret")
    resp = await client.get("/%2E%2E/secret.txt")
    assert resp.status == 404


def test_load_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'pin = "4321"\n'
        f'data_dir = "{tmp_path}"\n'
        'static_dir = "/opt/b3/editor"\n'
        'http_port = 80\n'
        'audio_device = "plughw:1,0"\n'
    )
    cfg = load_config(path)
    assert cfg.pin == "4321"
    assert cfg.http_port == 80
    assert cfg.audio_device == "plughw:1,0"
    assert cfg.mixer_control is None
    assert str(cfg.static_dir) == "/opt/b3/editor"


async def test_wrong_pin_is_delayed(client, config):
    import time
    t0 = time.monotonic()
    resp = await client.post("/api/login", json={"pin": "0000"})
    assert resp.status == 401
    assert time.monotonic() - t0 >= config.login_failure_delay


async def test_right_pin_is_not_delayed(client, config):
    import time
    t0 = time.monotonic()
    await client.post("/api/login", json={"pin": "1234"})
    assert time.monotonic() - t0 < config.login_failure_delay
