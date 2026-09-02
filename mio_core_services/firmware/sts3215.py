"""Minimal STS3215 (Feetech SMS/STS) helper: enable torque and move."""

from __future__ import annotations

import serial

INST_PING = 0x01
INST_WRITE = 0x03
ADDR_ID = 5
ADDR_TORQUE_ENABLE = 40
ADDR_ACC = 41
ADDR_LOCK = 55

DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUDRATE = 1_000_000
BROADCAST_ID = 254
CENTER_POSITION = 2048
POSITION_MAX = 4095


def _checksum(body: bytes) -> int:
    return (~sum(body)) & 0xFF


def _packet(servo_id: int, instruction: int, params: bytes = b"") -> bytes:
    length = len(params) + 2
    body = bytes([servo_id, length, instruction]) + params
    return bytes([0xFF, 0xFF]) + body + bytes([_checksum(body)])


def ping_packet(servo_id: int) -> bytes:
    return _packet(servo_id, INST_PING)


def write_packet(servo_id: int, address: int, data: bytes) -> bytes:
    return _packet(servo_id, INST_WRITE, bytes([address]) + data)


class STS3215Bus:
    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baudrate: int = DEFAULT_BAUDRATE,
    ) -> None:
        self._serial = serial.Serial(port, baudrate, timeout=0.05)

    def close(self) -> None:
        self._serial.close()

    def __enter__(self) -> STS3215Bus:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _write(self, servo_id: int, address: int, data: bytes) -> None:
        self._serial.write(write_packet(servo_id, address, data))
        self._serial.flush()
        self._serial.reset_input_buffer()

    def ping(self, servo_id: int) -> bool:
        self._serial.reset_input_buffer()
        self._serial.write(ping_packet(servo_id))
        self._serial.flush()
        header = self._serial.read(4)
        if len(header) < 4 or header[:2] != b"\xff\xff" or header[2] != servo_id:
            return False
        rest = self._serial.read(header[3])
        return len(rest) == header[3]

    def set_id(self, new_id: int, current_id: int = BROADCAST_ID) -> None:
        if not 1 <= new_id <= 253:
            raise ValueError(f"new_id must be 1–253, got {new_id}")
        if current_id != BROADCAST_ID and not 1 <= current_id <= 253:
            raise ValueError(f"current_id must be 1–253 or {BROADCAST_ID}, got {current_id}")
        self.enable_torque(current_id, False)
        self._write(current_id, ADDR_LOCK, bytes([0]))
        self._write(current_id, ADDR_ID, bytes([new_id]))
        self._write(new_id, ADDR_LOCK, bytes([1]))

    def enable_torque(self, servo_id: int = 1, enabled: bool = True) -> None:
        self._write(servo_id, ADDR_TORQUE_ENABLE, bytes([int(enabled)]))

    def move(
        self,
        position: int,
        servo_id: int = 1,
        speed: int = 1000,
        acc: int = 50,
    ) -> None:
        if not 0 <= position <= POSITION_MAX:
            raise ValueError(f"position must be 0–{POSITION_MAX}, got {position}")
        self.enable_torque(servo_id, True)
        payload = bytes(
            [
                acc,
                position & 0xFF,
                (position >> 8) & 0xFF,
                0,
                0,
                speed & 0xFF,
                (speed >> 8) & 0xFF,
            ]
        )
        self._write(servo_id, ADDR_ACC, payload)
