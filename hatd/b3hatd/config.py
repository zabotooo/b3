import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    pin: str
    data_dir: Path
    static_dir: Path
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    audio_device: str | None = None
    mixer_card: str | None = None
    mixer_control: str | None = None
    telemetry_interval: float = 0.05
    control_timeout: float = 3.0
    login_failure_delay: float = 1.0


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    raw["data_dir"] = Path(raw["data_dir"])
    raw["static_dir"] = Path(raw["static_dir"])
    raw["pin"] = str(raw["pin"])
    return Config(**raw)
