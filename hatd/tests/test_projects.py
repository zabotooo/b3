import pytest

from b3hatd.errors import B3Error
from b3hatd.projects import ProjectStore

PID = "0123456789abcdef0123456789abcdef"
PID2 = "fedcba9876543210fedcba9876543210"
SB3 = b"PK\x03\x04fake-zip-content"


def test_store_roundtrip(tmp_path):
    store = ProjectStore(tmp_path)
    meta = store.put(PID, "My robot", SB3)
    assert meta["id"] == PID and meta["name"] == "My robot"
    assert store.get(PID) == SB3
    assert [p["id"] for p in store.list()] == [PID]
    store.delete(PID)
    assert store.list() == []


def test_list_newest_first(tmp_path):
    store = ProjectStore(tmp_path)
    store.put(PID, "old", SB3)
    store.put(PID2, "new", SB3)
    assert [p["name"] for p in store.list()] == ["new", "old"]


@pytest.mark.parametrize("pid", ["../etc/passwd", "ABC", "0123456789abcdef0123456789abcdeg", ""])
def test_rejects_bad_ids(tmp_path, pid):
    store = ProjectStore(tmp_path)
    with pytest.raises(B3Error) as e:
        store.put(pid, "x", SB3)
    assert e.value.code == "bad_args"


def test_rejects_non_zip(tmp_path):
    with pytest.raises(B3Error):
        ProjectStore(tmp_path).put(PID, "x", b"not a zip")


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_rejects_bad_names(tmp_path, name):
    with pytest.raises(B3Error):
        ProjectStore(tmp_path).put(PID, name, SB3)


def test_get_missing(tmp_path):
    with pytest.raises(B3Error) as e:
        ProjectStore(tmp_path).get(PID)
    assert e.value.code == "not_found"


async def test_rest_requires_login(client):
    assert (await client.get("/api/projects")).status == 401


async def test_rest_roundtrip(authed):
    resp = await authed.put(f"/api/projects/{PID}?name=Robot", data=SB3)
    assert resp.status == 200
    assert (await resp.json())["name"] == "Robot"
    listing = await (await authed.get("/api/projects")).json()
    assert [p["id"] for p in listing] == [PID]
    resp = await authed.get(f"/api/projects/{PID}")
    assert await resp.read() == SB3
    assert (await authed.delete(f"/api/projects/{PID}")).status == 204
    assert (await authed.get(f"/api/projects/{PID}")).status == 404


async def test_rest_rejects_traversal(authed, config):
    resp = await authed.put("/api/projects/..%2F..%2Fevil?name=x", data=SB3)
    assert resp.status in (400, 404, 405)
    assert not list(config.data_dir.parent.rglob("evil*"))
