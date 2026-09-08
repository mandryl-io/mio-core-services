from pathlib import Path

import pytest

from mio_core_services.firmware.read_servo import _failure_message, _port_preflight


def test_preflight_rejects_missing_port(tmp_path: Path):
    with pytest.raises(SystemExit, match="does not exist"):
        _port_preflight(str(tmp_path / "missing"), 115_200)


def test_preflight_rejects_regular_file(tmp_path: Path):
    regular_file = tmp_path / "not-a-uart"
    regular_file.touch()
    with pytest.raises(SystemExit, match="not a character device"):
        _port_preflight(str(regular_file), 115_200)


def test_empty_receive_explains_forwarder_and_safety():
    message = _failure_message(
        1,
        "/dev/serial0",
        115_200,
        ["port: /dev/serial0 -> /dev/ttyAMA10"],
        TimeoutError("No read reply from servo 1 (rx=empty)"),
    )
    assert "received zero bytes" in message
    assert "inactive ESP32 forwarder" in message
    assert "No ID or calibration data was changed" in message


def test_invalid_receive_distinguishes_protocol_bytes():
    message = _failure_message(
        1,
        "/dev/serial0",
        115_200,
        [],
        TimeoutError("No read reply from servo 1 (rx=ffff0102)"),
    )
    assert "Bytes arrived" in message
    assert "baud-rate/protocol mismatch" in message
