"""install/make-release.sh, install/b3.service and (Task 6) install/install.sh."""

import subprocess
import tarfile
from pathlib import Path

import pytest

import b3hatd

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install"


@pytest.fixture(scope="module")
def archive(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("release")
    editor = tmp / "build"
    (editor / "static").mkdir(parents=True)
    (editor / "index.html").write_text("<h1>editor</h1>")
    (editor / "gui.js").write_text("1")
    (editor / "gui.js.map").write_text("{}")
    out = tmp / "b3.tar.gz"
    subprocess.run(["bash", str(INSTALL / "make-release.sh"), str(editor), str(out)], check=True)
    return out


def test_release_archive_layout(archive):
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        version = tar.extractfile("b3/VERSION").read().decode()
    assert version == b3hatd.__version__ + "\n"
    for name in ["b3/LICENSE", "b3/hatd/b3hatd/__main__.py", "b3/hatd/b3hatd/ws.py",
                 "b3/editor/index.html", "b3/editor/gui.js",
                 "b3/install/install.sh", "b3/install/b3.service"]:
        assert name in names
    assert not [n for n in names if n.endswith(".map") or "/tests/" in n or "__pycache__" in n]


def test_release_archive_files_belong_to_root(archive):
    # tar run by root restores owners; files must not end up owned by the CI runner's uid
    with tarfile.open(archive) as tar:
        assert {(m.uid, m.gid) for m in tar.getmembers()} == {(0, 0)}


def test_service_unit_runs_hatd_from_the_release_as_b3():
    unit = (INSTALL / "b3.service").read_text()
    assert "User=b3" in unit
    assert "Environment=PYTHONPATH=/opt/b3/hatd" in unit
    assert "ExecStart=/usr/bin/python3 -P -m b3hatd --config /var/lib/b3/config.toml" in unit
    assert "Restart=on-failure" in unit
    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in unit  # port 80 without root
    assert "WorkingDirectory=/var/lib/b3" in unit  # lgpio writes notify files in the cwd
    assert "ReadWritePaths=/var/lib/b3" in unit


STUBS = {
    # every system command install.sh calls; each logs "name args" to $STUB_LOG
    "apt-get": "",
    "systemctl": "",
    "useradd": "",
    "userdel": "",
    "chown": "",
    "reboot": "",
    "id": "exit 1",  # no b3 user yet, even on a Pi where B3 is installed
    "curl": "exit 22",  # tests that install from GitHub expect the download to fail
    "raspi-config": (
        'case "$2" in get_serial_hw) echo "${FAKE_SERIAL_HW:-0}";; '
        'get_serial_cons) echo "${FAKE_SERIAL_CONS:-1}";; esac'
    ),
    "aplay": '[ -n "${FAKE_HEADPHONES:-}" ] && echo "card 0: Headphones [bcm2835 Headphones], device 0: x"; true',
}


@pytest.fixture
def system(tmp_path, archive):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in STUBS.items():
        path = stubs / name
        path.write_text(f'#!/bin/bash\necho "{name} $*" >> "$STUB_LOG"\n{body}\n')
        path.chmod(0o755)
    root = tmp_path / "root"
    log = tmp_path / "stub.log"
    log.touch()

    def run(*args, **env):
        full_env = {"PATH": f"{stubs}:/usr/bin:/bin", "B3_ROOT": str(root), "STUB_LOG": str(log),
                    "B3_ARCHIVE": str(archive), **env}
        full_env = {k: v for k, v in full_env.items() if v is not None}
        return subprocess.run(["bash", str(INSTALL / "install.sh"), *args], env=full_env,
                              capture_output=True, text=True)

    run.root = root
    run.log = log
    return run


def _config(system):
    from b3hatd.config import load_config
    return load_config(system.root / "var/lib/b3/config.toml")


def test_fresh_install(system):
    result = system()
    assert result.returncode == 0, result.stderr
    root = system.root
    assert (root / "opt/b3/VERSION").read_text() == b3hatd.__version__ + "\n"
    assert (root / "opt/b3/hatd/b3hatd/__main__.py").is_file()
    assert (root / "opt/b3/editor/index.html").is_file()
    assert (root / "etc/systemd/system/b3.service").read_text() == (INSTALL / "b3.service").read_text()
    cfg = _config(system)
    assert len(cfg.pin) == 4 and cfg.pin.isdigit()
    assert cfg.http_port == 80
    assert str(cfg.data_dir) == "/var/lib/b3"
    assert str(cfg.static_dir) == "/opt/b3/editor"
    assert cfg.audio_device is None
    assert (root / "var/lib/b3/config.toml").stat().st_mode & 0o777 == 0o600
    log = system.log.read_text()
    assert "apt-get install -y -q python3-build-hat python3-aiohttp alsa-utils" in log
    assert "useradd --system --user-group --home-dir /var/lib/b3 --no-create-home" in log
    assert "systemctl enable b3" in log and "systemctl restart b3" in log
    assert "do_serial" not in log, "UART was already set up"
    assert f"PIN: {cfg.pin}" in result.stdout
    assert ".local" in result.stdout
    assert "reboot" not in result.stdout.lower()


def test_headphones_become_the_audio_device(system):
    assert system(FAKE_HEADPHONES="1").returncode == 0
    assert _config(system).audio_device == "plughw:CARD=Headphones,DEV=0"


def test_uart_changes_ask_for_a_reboot(system):
    result = system(FAKE_SERIAL_HW="1", FAKE_SERIAL_CONS="0")
    assert result.returncode == 0, result.stderr
    log = system.log.read_text()
    assert "raspi-config nonint do_serial_hw 0" in log
    assert "raspi-config nonint do_serial_cons 1" in log
    assert "sudo reboot" in result.stdout
    assert "reboot" not in [line.split()[0] for line in log.splitlines()], "never reboots by itself in tests"


def test_update_keeps_config_and_projects(system):
    assert system().returncode == 0
    data = system.root / "var/lib/b3"
    config = data / "config.toml"
    config.write_text(config.read_text().replace(f'pin = "{_config(system).pin}"', 'pin = "4242"'))
    (data / "projects").mkdir(exist_ok=True)
    (data / "projects" / "abc.sb3").write_text("project")
    (system.root / "opt/b3/editor/old.js").write_text("old")
    result = system()
    assert result.returncode == 0, result.stderr
    assert _config(system).pin == "4242"
    assert (data / "projects" / "abc.sb3").read_text() == "project"
    assert not (system.root / "opt/b3/editor/old.js").exists(), "files of the old release are gone"
    assert "PIN: 4242" in result.stdout


def test_failed_download_keeps_old_install(system):
    assert system().returncode == 0
    system.log.write_text("")
    result = system(B3_ARCHIVE=None)
    assert result.returncode != 0
    assert "https://github.com/zabotooo/b3/releases/latest/download/b3.tar.gz" in result.stderr
    assert (system.root / "opt/b3/VERSION").is_file()
    assert "systemctl stop b3" not in system.log.read_text()


def test_failed_download_changes_nothing_on_the_system(system):
    result = system(B3_ARCHIVE=None, FAKE_SERIAL_HW="1", FAKE_SERIAL_CONS="0")
    assert result.returncode != 0
    assert system.log.read_text().splitlines()[0].startswith("curl "), "downloads before anything else"
    assert "raspi-config nonint do_serial" not in system.log.read_text()
    assert "apt-get" not in system.log.read_text()


def test_install_unpacks_without_archive_owners():
    assert "tar --no-same-owner -xzf" in (INSTALL / "install.sh").read_text()


def test_specific_version_url(system):
    result = system(B3_ARCHIVE=None, B3_VERSION="0.2.0")
    assert "https://github.com/zabotooo/b3/releases/download/v0.2.0/b3.tar.gz" in result.stderr


def test_uninstall_keeps_data_unless_purged(system):
    assert system().returncode == 0
    result = system("uninstall")
    assert result.returncode == 0, result.stderr
    assert not (system.root / "opt/b3").exists()
    assert not (system.root / "etc/systemd/system/b3.service").exists()
    assert (system.root / "var/lib/b3/config.toml").is_file()
    assert "systemctl disable --now b3" in system.log.read_text()
    assert "--purge" in result.stdout
    assert system("uninstall", "--purge").returncode == 0
    assert not (system.root / "var/lib/b3").exists()
    assert "userdel b3" in system.log.read_text()


def test_unknown_command_fails(system):
    result = system("frobnicate")
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
