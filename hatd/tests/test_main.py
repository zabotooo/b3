import pytest

from b3hatd.__main__ import build, main, parse_sim_devices
from b3hatd.keys import BACKEND, SOUND
from b3hatd.sim import SimBackend


def _config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'pin = "1111"\n'
        f'data_dir = "{tmp_path}"\n'
        f'static_dir = "{tmp_path / "editor"}"\n'
        'audio_device = "plughw:1,0"\n'
        'mixer_control = "PCM"\n'
    )
    return cfg


def test_build_sim(tmp_path):
    app = build(_config(tmp_path), sim=True)
    backend = app[BACKEND]
    assert isinstance(backend, SimBackend)
    assert backend.typeids() == {"A": 48, "B": 48, "C": 61, "D": 62}
    assert app[SOUND].device == "plughw:1,0"
    assert app[SOUND].mixer_control == "PCM"
    assert (tmp_path / "sounds").is_dir()


def test_build_sim_with_other_devices(tmp_path):
    app = build(_config(tmp_path), sim=True, sim_devices="A=8, B=64,C=34")
    assert app[BACKEND].typeids() == {"A": 8, "B": 64, "C": 34, "D": None}


@pytest.mark.parametrize("text", ["E=8", "A=x", "A8", "A=8,A"])
def test_bad_sim_devices_are_rejected(text):
    with pytest.raises(ValueError):
        parse_sim_devices(text)


async def test_sim_sound_needs_no_aplay(tmp_path):
    player = build(_config(tmp_path), sim=True)[SOUND]
    proc = await player.runner.spawn(["aplay", "-q", "x.wav"])
    assert await proc.wait() == 0
    proc.kill()
    assert await player.runner.run(["amixer", "sset", "PCM", "50%"]) == 0


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "b3hatd 0.1.0"
