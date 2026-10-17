import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from b3hatd.app import create_app
from b3hatd.config import Config
from b3hatd.sim import SimBackend
from b3hatd.sound import SoundPlayer
from tests.fakes import FakeRunner


@pytest.fixture
def config(tmp_path):
    return Config(
        pin="1234",
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "static",
        telemetry_interval=0.02,
        control_timeout=0.3,
        login_failure_delay=0.2,
    )


@pytest.fixture
def backend():
    return SimBackend(max_dps=100_000)


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def sound(config, runner):
    return SoundPlayer(config.data_dir / "sounds", runner=runner, beep_forever_s=0.2)


@pytest_asyncio.fixture
async def client(config, backend, sound):
    app = create_app(config, backend, sound)
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
async def authed(client):
    resp = await client.post("/api/login", json={"pin": "1234"})
    assert resp.status == 200
    return client
