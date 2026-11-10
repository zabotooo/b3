"""Positional moves use B3's position-PID gains instead of buildhat's (hardware-notes.md
"Motor stopping accuracy")."""

import threading
import types

from b3hatd.buildhat_backend import BuildHatBackend, damp_positional_moves
from b3hatd.devices import Kind


class RampMotor:
    """The parts of a buildhat Motor that _run_positional_ramp touches."""

    def __init__(self, release):
        self.port = 2
        self._interval = 10
        self._rpm = False
        self._release = release
        self._hat = types.SimpleNamespace(rampftr=[[], [], [], []])
        self.written = []
        self.coasted = threading.Event()

    def _write(self, cmd):
        self.written.append(cmd)
        self._hat.rampftr[self.port].pop().set_result(None)  # the firmware reports the ramp done

    def coast(self):
        self.coasted.set()


def test_ramp_sends_damped_gains():
    motor = RampMotor(release=False)
    damp_positional_moves(motor)
    motor._run_positional_ramp(0.0, 0.25, 50)
    assert motor.written == [
        "port 2; select 0 ; selrate 10; pid 2 0 1 s4 0.0027777778 0 8 0 0.6 3 0.01; "
        "set ramp 0.0 0.25 0.1 0\r"
    ]
    assert not motor.coasted.is_set()


def test_ramp_still_releases_like_buildhat():
    motor = RampMotor(release=True)
    damp_positional_moves(motor)
    motor._run_positional_ramp(0.5, 0.0, -20)
    assert "set ramp 0.5 0.0 0.5 0\r" in motor.written[0]
    assert motor.coasted.is_set()


def test_encoder_motors_get_damped_moves():
    opened = []

    class Motor:
        def __init__(self, port):
            opened.append(self)

    backend = BuildHatBackend.__new__(BuildHatBackend)
    backend._buildhat = types.SimpleNamespace(Motor=Motor)
    for kind in (Kind.MOTOR_ABS, Kind.MOTOR_REL):
        dev = backend._open("A", kind)
        assert dev._run_positional_ramp.__name__ == "damped_ramp"
