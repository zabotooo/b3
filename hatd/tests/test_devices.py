import pytest

from b3hatd.devices import CATALOG, Kind, check, lookup
from b3hatd.errors import B3Error

USER_LISTED_TYPEIDS = [1, 2, 8, 34, 35, 37, 38, 46, 47, 48, 49, 61, 62, 63, 64, 65, 75, 76]


def test_all_supported_devices_are_in_catalog():
    for typeid in USER_LISTED_TYPEIDS:
        assert typeid in CATALOG


def test_lookup():
    assert lookup(48).kind is Kind.MOTOR_ABS
    assert lookup(47).kind is Kind.MOTOR_REL
    assert lookup(2).kind is Kind.MOTOR_PASSIVE
    assert lookup(999) is None
    assert lookup(None) is None


def test_check_accepts_matching_device():
    check("motor.position", "A", 48)
    check("motor.seconds", "B", 2)
    check("distance_lights", "C", 62)


def test_check_wrong_device_message():
    with pytest.raises(B3Error) as e:
        check("motor.position", "A", 47)
    assert e.value.code == "wrong_device"
    assert e.value.port == "A"
    assert e.value.message == "Port A: expected motor with absolute position, found Technic XL Motor"


def test_check_empty_port():
    with pytest.raises(B3Error) as e:
        check("motor.power", "D", None)
    assert e.value.code == "no_device"
    assert e.value.message == "Port D: expected motor, found nothing"


def test_check_unknown_device():
    with pytest.raises(B3Error) as e:
        check("light", "B", 999)
    assert e.value.code == "wrong_device"
    assert e.value.message == "Port B: expected Light, found unknown device 999"


def test_passive_motor_has_no_encoder():
    with pytest.raises(B3Error):
        check("motor.degrees", "A", 1)


def test_error_to_dict():
    assert B3Error("x", "msg").to_dict() == {"code": "x", "message": "msg"}
    assert B3Error("x", "msg", port="A").to_dict() == {"code": "x", "message": "msg", "port": "A"}
