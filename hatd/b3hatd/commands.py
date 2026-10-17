"""WebSocket commands: validation and dispatch."""

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from aiohttp import web

from .devices import MATRIX_COLORS, PORTS, check
from .errors import B3Error
from .keys import BACKEND, CONTROL, SOUND

Handler = Callable[["Context", dict], Awaitable[dict | None]]
_HANDLERS: dict[str, tuple[Handler, bool]] = {}


@dataclass
class Context:
    app: web.Application
    client_id: str

    @property
    def backend(self):
        return self.app[BACKEND]

    @property
    def sound(self):
        return self.app[SOUND]

    @property
    def control(self):
        return self.app[CONTROL]


def command(name: str, actuating: bool = True):
    def register(fn: Handler) -> Handler:
        _HANDLERS[name] = (fn, actuating)
        return fn
    return register


async def dispatch(ctx: Context, cmd: str, args: dict) -> dict:
    entry = _HANDLERS.get(cmd)
    if entry is None:
        raise B3Error("unknown_cmd", f"Unknown command {cmd}")
    fn, actuating = entry
    if actuating and not ctx.control.is_controller(ctx.client_id):
        raise B3Error("not_controller", "Another device controls the robot. Take control first.")
    result = await fn(ctx, args)
    return result if result is not None else {}


# --- validators -------------------------------------------------------

def port(args: dict, key: str = "port") -> str:
    value = args.get(key)
    if value not in PORTS:
        raise B3Error("bad_args", f"{key} must be one of A, B, C, D")
    return value


def number(args: dict, key: str, lo: float, hi: float, integer: bool = False):
    value = args.get(key)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not lo <= value <= hi):
        raise B3Error("bad_args", f"{key} must be a number between {lo} and {hi}")
    if integer:
        if value != int(value):
            raise B3Error("bad_args", f"{key} must be a whole number")
        return int(value)
    return float(value)


def choice(args: dict, key: str, options: tuple[str, ...]) -> str:
    value = args.get(key)
    if value not in options:
        raise B3Error("bad_args", f"{key} must be one of {', '.join(options)}")
    return value


def boolean(args: dict, key: str) -> bool:
    value = args.get(key)
    if not isinstance(value, bool):
        raise B3Error("bad_args", f"{key} must be true or false")
    return value


def require(ctx: Context, capability: str, p: str) -> None:
    check(capability, p, ctx.backend.typeids()[p])


# --- session commands -------------------------------------------------

@command("ping", actuating=False)
async def _ping(ctx: Context, args: dict):
    ctx.control.ping(ctx.client_id)


@command("control.claim", actuating=False)
async def _claim(ctx: Context, args: dict):
    await ctx.control.claim(ctx.client_id)
    return {"holder": ctx.client_id}


# --- motors -----------------------------------------------------------

_UNITS = ("degrees", "seconds")
_MAX_VALUE = {"degrees": 1_000_000, "seconds": 3600}
_MD5 = re.compile(r"^[0-9a-f]{32}$")


def _speed(args: dict, key: str = "speed") -> int:
    return number(args, key, -100, 100, integer=True)


async def _run_for(ctx: Context, p: str, unit: str, value: float, speed: int) -> None:
    if value == 0:
        return  # nothing to do; a zero-length move may never report completion
    if unit == "degrees":
        await ctx.backend.motor_run_for_degrees(p, value, speed)
    else:
        await ctx.backend.motor_run_for_seconds(p, value, speed)


@command("motor.run_for")
async def _motor_run_for(ctx: Context, args: dict):
    p = port(args)
    unit = choice(args, "unit", _UNITS)
    value = number(args, "value", 0, _MAX_VALUE[unit])
    speed = _speed(args)
    if speed == 0:
        raise B3Error("bad_args", "speed must not be 0")
    require(ctx, f"motor.{unit}", p)
    await _run_for(ctx, p, unit, value, speed)


@command("motor.start")
async def _motor_start(ctx: Context, args: dict):
    p = port(args)
    speed = _speed(args)
    require(ctx, "motor.power", p)
    await ctx.backend.motor_start(p, speed)


@command("motor.stop")
async def _motor_stop(ctx: Context, args: dict):
    p = port(args)
    require(ctx, "motor.power", p)
    await ctx.backend.motor_stop(p)


@command("motor.go_to")
async def _motor_go_to(ctx: Context, args: dict):
    p = port(args)
    position = number(args, "position", -360, 360, integer=True)
    direction = choice(args, "direction", ("shortest", "cw", "ccw"))
    speed = number(args, "speed", 1, 100, integer=True)
    require(ctx, "motor.position", p)
    await ctx.backend.motor_go_to(p, position, direction, speed)


# --- movement (motor pair) --------------------------------------------

def _pair(args: dict) -> tuple[str, str]:
    left, right = port(args, "left"), port(args, "right")
    if left == right:
        raise B3Error("bad_args", "left and right must be different ports")
    return left, right


@command("pair.run_for")
async def _pair_run_for(ctx: Context, args: dict):
    left, right = _pair(args)
    unit = choice(args, "unit", _UNITS)
    wheels = []
    for side, p in (("left", left), ("right", right)):
        value = number(args, f"{side}_value", 0, _MAX_VALUE[unit])
        speed = _speed(args, f"{side}_speed")
        require(ctx, f"motor.{unit}", p)
        if value > 0 and speed != 0:
            wheels.append((p, value, speed))
    await asyncio.gather(*(_run_for(ctx, p, unit, v, s) for p, v, s in wheels))


@command("pair.start")
async def _pair_start(ctx: Context, args: dict):
    left, right = _pair(args)
    speeds = _speed(args, "left_speed"), _speed(args, "right_speed")
    for p in (left, right):
        require(ctx, "motor.power", p)
    await asyncio.gather(ctx.backend.motor_start(left, speeds[0]),
                         ctx.backend.motor_start(right, speeds[1]))


@command("pair.stop")
async def _pair_stop(ctx: Context, args: dict):
    left, right = _pair(args)
    for p in (left, right):
        require(ctx, "motor.power", p)
    await asyncio.gather(ctx.backend.motor_stop(left), ctx.backend.motor_stop(right))


# --- lights -------------------------------------------------------------

@command("light.set")
async def _light_set(ctx: Context, args: dict):
    p = port(args)
    brightness = number(args, "brightness", 0, 100, integer=True)
    require(ctx, "light", p)
    await ctx.backend.light_set(p, brightness)


@command("matrix.set")
async def _matrix_set(ctx: Context, args: dict):
    p = port(args)
    raw = args.get("pixels")
    if not isinstance(raw, list) or len(raw) != 9:
        raise B3Error("bad_args", "pixels must be a list of 9 [color, brightness] pairs")
    pixels = []
    for item in raw:
        if (not isinstance(item, list) or len(item) != 2 or item[0] not in MATRIX_COLORS):
            raise B3Error("bad_args", f"pixel colors must be one of {', '.join(MATRIX_COLORS)}")
        pixels.append((item[0], number({"b": item[1]}, "b", 0, 10, integer=True)))
    require(ctx, "matrix", p)
    await ctx.backend.matrix_set(p, pixels)


@command("sensor.lights")
async def _sensor_lights(ctx: Context, args: dict):
    p = port(args)
    raw = args.get("values")
    if not isinstance(raw, list) or len(raw) != 4:
        raise B3Error("bad_args", "values must be a list of 4 brightness values")
    values = [number({"v": v}, "v", 0, 100, integer=True) for v in raw]
    require(ctx, "distance_lights", p)
    await ctx.backend.sensor_lights(p, values)


# --- sound ----------------------------------------------------------------

@command("sound.play")
async def _sound_play(ctx: Context, args: dict):
    md5 = args.get("md5")
    if not isinstance(md5, str) or not _MD5.match(md5):
        raise B3Error("bad_args", "md5 must be 32 hex characters")
    await ctx.sound.play(md5, boolean(args, "wait"))


@command("sound.beep")
async def _sound_beep(ctx: Context, args: dict):
    note = number(args, "note", 44, 123, integer=True)
    duration = None if args.get("duration") is None else number(args, "duration", 0.01, 60)
    await ctx.sound.beep(note, duration)


@command("sound.stop")
async def _sound_stop(ctx: Context, args: dict):
    await ctx.sound.stop()


@command("sound.volume")
async def _sound_volume(ctx: Context, args: dict):
    await ctx.sound.set_volume(number(args, "value", 0, 100, integer=True))


# --- everything -------------------------------------------------------------

@command("program.running")
async def _program_running(ctx: Context, args: dict):
    running = args.get("running")
    if not isinstance(running, bool):
        raise B3Error("bad_args", "running must be true or false")
    ctx.backend.set_program_running(running)


@command("stop_all")
async def _stop_all(ctx: Context, args: dict):
    await ctx.backend.stop_all()
    await ctx.sound.stop()
