"""Catalogue of Powered Up devices supported by the Build HAT."""

from dataclasses import dataclass
from enum import Enum

from .errors import B3Error

PORTS = ("A", "B", "C", "D")

# Colour names accepted by buildhat.Matrix (index 0-10)
MATRIX_COLORS = ("black", "pink", "lilac", "blue", "cyan", "turquoise",
                 "green", "yellow", "orange", "red", "white")


class Kind(str, Enum):
    MOTOR_ABS = "motor_abs"
    MOTOR_REL = "motor_rel"
    MOTOR_PASSIVE = "motor_passive"
    LIGHT = "light"
    MATRIX = "matrix"
    COLOR = "color"
    DISTANCE = "distance"
    FORCE = "force"
    COLOR_DISTANCE = "color_distance"
    WEDO_TILT = "wedo_tilt"
    WEDO_MOTION = "wedo_motion"


@dataclass(frozen=True)
class DeviceInfo:
    typeid: int
    name: str
    kind: Kind


_DEVICES = [
    DeviceInfo(1, "Simple Motor", Kind.MOTOR_PASSIVE),
    DeviceInfo(2, "Train Motor", Kind.MOTOR_PASSIVE),
    DeviceInfo(8, "Light", Kind.LIGHT),
    DeviceInfo(34, "WeDo 2.0 Tilt Sensor", Kind.WEDO_TILT),
    DeviceInfo(35, "WeDo 2.0 Motion Sensor", Kind.WEDO_MOTION),
    DeviceInfo(37, "Color & Distance Sensor", Kind.COLOR_DISTANCE),
    DeviceInfo(38, "BOOST Interactive Motor", Kind.MOTOR_REL),
    DeviceInfo(46, "Technic Large Motor", Kind.MOTOR_REL),
    DeviceInfo(47, "Technic XL Motor", Kind.MOTOR_REL),
    DeviceInfo(48, "Medium Angular Motor (Cyan)", Kind.MOTOR_ABS),
    DeviceInfo(49, "Large Angular Motor (Cyan)", Kind.MOTOR_ABS),
    DeviceInfo(61, "Color Sensor", Kind.COLOR),
    DeviceInfo(62, "Distance Sensor", Kind.DISTANCE),
    DeviceInfo(63, "Force Sensor", Kind.FORCE),
    DeviceInfo(64, "3x3 Color Light Matrix", Kind.MATRIX),
    DeviceInfo(65, "Small Angular Motor", Kind.MOTOR_ABS),
    DeviceInfo(75, "Medium Angular Motor (Grey)", Kind.MOTOR_ABS),
    DeviceInfo(76, "Large Angular Motor (Grey)", Kind.MOTOR_ABS),
]

CATALOG: dict[int, DeviceInfo] = {d.typeid: d for d in _DEVICES}

ENCODER_MOTORS = frozenset({Kind.MOTOR_ABS, Kind.MOTOR_REL})
ALL_MOTORS = ENCODER_MOTORS | {Kind.MOTOR_PASSIVE}

# capability -> (allowed kinds, what the user is told was expected)
CAPABILITIES: dict[str, tuple[frozenset, str]] = {
    "motor.degrees": (ENCODER_MOTORS, "motor with encoder"),
    "motor.seconds": (ALL_MOTORS, "motor"),
    "motor.power": (ALL_MOTORS, "motor"),
    "motor.position": (frozenset({Kind.MOTOR_ABS}), "motor with absolute position"),
    "light": (frozenset({Kind.LIGHT}), "Light"),
    "matrix": (frozenset({Kind.MATRIX}), "3x3 Color Light Matrix"),
    "distance_lights": (frozenset({Kind.DISTANCE}), "Distance Sensor"),
}


def lookup(typeid: int | None) -> DeviceInfo | None:
    if typeid is None:
        return None
    return CATALOG.get(typeid)


def check(capability: str, port: str, typeid: int | None) -> None:
    """Raise B3Error unless the device on `port` supports `capability`."""
    kinds, expected = CAPABILITIES[capability]
    if typeid is None:
        raise B3Error("no_device", f"Port {port}: expected {expected}, found nothing", port=port)
    info = lookup(typeid)
    if info is None:
        raise B3Error("wrong_device", f"Port {port}: expected {expected}, found unknown device {typeid}", port=port)
    if info.kind not in kinds:
        raise B3Error("wrong_device", f"Port {port}: expected {expected}, found {info.name}", port=port)
