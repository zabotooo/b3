import asyncio
import hashlib
import io
import wave

import pytest

from b3hatd.errors import B3Error
from b3hatd.sound import SoundPlayer
from b3hatd.tone import note_to_hz, write_tone
from tests.fakes import FakeRunner


def make_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 80)
    return buf.getvalue()


WAV = make_wav()
WAV_MD5 = hashlib.md5(WAV).hexdigest()


@pytest.fixture
def player(tmp_path):
    return SoundPlayer(tmp_path / "sounds", runner=FakeRunner(), device="plughw:1,0")


def test_note_to_hz():
    assert note_to_hz(69) == pytest.approx(440.0)
    assert note_to_hz(60) == pytest.approx(261.63, abs=0.01)


def test_write_tone(tmp_path):
    path = tmp_path / "t.wav"
    write_tone(path, 440.0, 0.1)
    with wave.open(str(path)) as w:
        assert w.getframerate() == 22050
        assert w.getnframes() == 2205


def test_store_and_has(player):
    assert not player.has(WAV_MD5)
    player.store(WAV_MD5, WAV)
    assert player.has(WAV_MD5)


def test_store_rejects_checksum_mismatch(player):
    with pytest.raises(B3Error) as e:
        player.store("0" * 32, WAV)
    assert e.value.code == "bad_args"


def test_store_rejects_non_wav(player):
    mp3 = b"ID3\x03\x00" + b"\x00" * 50
    with pytest.raises(B3Error) as e:
        player.store(hashlib.md5(mp3).hexdigest(), mp3)
    assert e.value.message == "Only WAV sounds are supported"


def test_bad_md5_format(player):
    with pytest.raises(B3Error):
        player.has("../../etc/passwd")


async def test_play_without_wait(player):
    player.store(WAV_MD5, WAV)
    await player.play(WAV_MD5, wait=False)
    args, _ = player.runner.spawned[0]
    assert args[:4] == ["aplay", "-q", "-D", "plughw:1,0"]
    assert args[-1].endswith(f"{WAV_MD5}.wav")


async def test_play_until_done_waits(player):
    player.store(WAV_MD5, WAV)
    task = asyncio.create_task(player.play(WAV_MD5, wait=True))
    await asyncio.sleep(0.01)
    assert not task.done()
    player.runner.spawned[0][1].finish()
    await asyncio.wait_for(task, 1)


async def test_play_missing_sound(player):
    with pytest.raises(B3Error) as e:
        await player.play(WAV_MD5, wait=False)
    assert e.value.code == "not_found"


async def test_stop_kills_everything(player):
    player.store(WAV_MD5, WAV)
    await player.play(WAV_MD5, wait=False)
    waiting = asyncio.create_task(player.play(WAV_MD5, wait=True))
    await asyncio.sleep(0.01)
    await player.stop()
    await asyncio.wait_for(waiting, 1)
    assert all(proc.killed for _, proc in player.runner.spawned)


async def test_beep_generates_and_caches(player):
    task = asyncio.create_task(player.beep(60, 0.1))
    for _ in range(200):
        if player.runner.spawned:
            break
        await asyncio.sleep(0.01)
    player.runner.spawned[0][1].finish()
    await asyncio.wait_for(task, 2)
    assert (player.cache_dir / "beep-60-100.wav").exists()


async def test_volume_uses_amixer_when_configured(tmp_path):
    runner = FakeRunner()
    player = SoundPlayer(tmp_path, runner=runner, mixer_card="1", mixer_control="PCM")
    await player.set_volume(40)
    assert runner.ran == [["amixer", "-q", "-c", "1", "sset", "PCM", "40%"]]
    assert player.volume == 40


async def test_volume_without_mixer_is_stored_only(player):
    await player.set_volume(10)
    assert player.runner.ran == []
    assert player.volume == 10


async def test_sound_upload_endpoint(authed):
    resp = await authed.head(f"/api/sounds/{WAV_MD5}")
    assert resp.status == 404
    resp = await authed.put(f"/api/sounds/{WAV_MD5}", data=WAV)
    assert resp.status == 204
    resp = await authed.head(f"/api/sounds/{WAV_MD5}")
    assert resp.status == 200


async def test_sound_upload_rejects_mismatch(authed):
    resp = await authed.put(f"/api/sounds/{'0' * 32}", data=WAV)
    assert resp.status == 400


async def test_cancelled_play_until_done_kills_aplay(player):
    player.store(WAV_MD5, WAV)
    task = asyncio.create_task(player.play(WAV_MD5, wait=True))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert player.runner.spawned[0][1].killed


async def test_beep_cache_is_bounded(player):
    for ms in range(60):
        task = asyncio.create_task(player.beep(60, 0.001 * (ms + 1)))
        while len(player.runner.spawned) <= ms:
            await asyncio.sleep(0.001)
        player.runner.spawned[ms][1].finish()
        await task
    assert len(list(player.cache_dir.glob("beep-*.wav"))) <= 50
