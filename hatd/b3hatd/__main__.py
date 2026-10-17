"""python3 -m b3hatd --config /var/lib/b3/config.toml [--sim [--sim-devices A=48,B=8]]"""

import argparse
import logging
import sys
from pathlib import Path

from aiohttp import web

from . import __version__
from .app import create_app
from .config import load_config
from .keys import EXIT_CODE
from .devices import PORTS
from .sound import SoundPlayer

SIM_DEVICES = "A=48,B=48,C=61,D=62"


def parse_sim_devices(text: str) -> dict[str, int]:
    """'A=48, B=8' -> {'A': 48, 'B': 8}; ports not named stay empty."""
    devices: dict[str, int] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        port, sep, typeid = item.partition("=")
        port = port.strip()
        if not sep or port not in PORTS or not typeid.strip().isdigit():
            raise ValueError(f"bad --sim-devices entry {item!r}; expected e.g. A=48")
        devices[port] = int(typeid)
    return devices


def build(config_path: Path, sim: bool, sim_devices: str = SIM_DEVICES) -> web.Application:
    config = load_config(config_path)
    runner = None
    if sim:
        from .sim import SilentRunner, SimBackend
        backend = SimBackend()
        for port, typeid in parse_sim_devices(sim_devices).items():
            backend.attach(port, typeid)
        runner = SilentRunner()
    else:
        from .buildhat_backend import BuildHatBackend
        backend = BuildHatBackend()
    sound = SoundPlayer(config.data_dir / "sounds", runner=runner, device=config.audio_device,
                        mixer_card=config.mixer_card, mixer_control=config.mixer_control)
    return create_app(config, backend, sound)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="b3hatd")
    parser.add_argument("--version", action="version", version=f"b3hatd {__version__}")
    parser.add_argument("--config", type=Path, default=Path("/var/lib/b3/config.toml"))
    parser.add_argument("--sim", action="store_true", help="use the simulator instead of a Build HAT")
    parser.add_argument("--sim-devices", default=SIM_DEVICES,
                        help=f"simulated devices as PORT=typeid list (default {SIM_DEVICES})")
    args = parser.parse_args(argv)
    try:
        parse_sim_devices(args.sim_devices)
    except ValueError as e:
        parser.error(str(e))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config(args.config)
    app = build(args.config, args.sim, args.sim_devices)
    web.run_app(app, host=config.http_host, port=config.http_port, shutdown_timeout=5)
    if app[EXIT_CODE]["code"]:
        sys.exit(app[EXIT_CODE]["code"])


if __name__ == "__main__":
    main()
