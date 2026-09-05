"""Minimal STS3215 (Feetech SMS/STS) helper: enable torque, move, and read."""

from __future__ import annotations

import time

import serial

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
INST_SYNC_WRITE = 0x83
ADDR_ID = 5
ADDR_TORQUE_ENABLE = 40
ADDR_ACC = 41
ADDR_GOAL_POSITION = 42
ADDR_GOAL_SPEED = 46
ADDR_LOCK = 55
ADDR_PRESENT_POSITION = 56

DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUDRATE = 1_000_000
BROADCAST_ID = 254
CENTER_POSITION = 2048
POSITION_MAX = 4095
READ_TIMEOUT = 0.15
READ_ATTEMPTS = 5


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


def read_packet(servo_id: int, address: int, length: int) -> bytes:
    return _packet(servo_id, INST_READ, bytes([address, length]))


def _status_params(
    buf: bytes, servo_id: int, n_params: int, tx_packet: bytes
) -> bytes | None:
    if buf.startswith(tx_packet):
        buf = buf[len(tx_packet) :]
    i = 0
    while i + 6 <= len(buf):
        if buf[i] != 0xFF or buf[i + 1] != 0xFF:
            i += 1
            continue
        length = buf[i + 3]
        end = i + 4 + length
        if length < 2 or end > len(buf):
            i += 1
            continue
        packet = bytes(buf[i:end])
        if packet == tx_packet:
            i = end
            continue
        body = packet[2:]
        if packet[2] != servo_id or _checksum(body[:-1]) != body[-1]:
            i += 1
            continue
        params = body[3:-1]
        if len(params) != n_params:
            i += 1
            continue
        return params
    return None


class STS3215Bus:
    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baudrate: int = DEFAULT_BAUDRATE,
    ) -> None:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baudrate
        ser.timeout = 0.1
        ser.write_timeout = 0.1
        ser.dtr = False
        ser.open()
        self._serial = ser
        time.sleep(0.05)
        self._serial.reset_input_buffer()

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

    def _recv(self, servo_id: int, tx_packet: bytes, n_params: int) -> bytes:
        deadline = time.monotonic() + READ_TIMEOUT
        buf = bytearray()
        old = self._serial.timeout
        self._serial.timeout = 0.02
        try:
            while time.monotonic() < deadline:
                chunk = self._serial.read(max(1, self._serial.in_waiting))
                if not chunk:
                    continue
                buf.extend(chunk)
                data = _status_params(buf, servo_id, n_params, tx_packet)
                if data is not None:
                    return data
        finally:
            self._serial.timeout = old
        detail = buf.hex() if buf else "empty"
        raise TimeoutError(f"No read reply from servo {servo_id} (rx={detail})")

    def _read(self, servo_id: int, address: int, length: int) -> bytes:
        packet = read_packet(servo_id, address, length)
        last_error: Exception | None = None
        for _ in range(READ_ATTEMPTS):
            self._serial.reset_input_buffer()
            self._serial.write(packet)
            self._serial.flush()
            try:
                return self._recv(servo_id, packet, length)
            except TimeoutError as exc:
                last_error = exc
        raise last_error or TimeoutError(f"No read reply from servo {servo_id}")

    def ping(self, servo_id: int) -> bool:
        packet = ping_packet(servo_id)
        self._serial.reset_input_buffer()
        self._serial.write(packet)
        self._serial.flush()
        try:
            self._recv(servo_id, packet, 0)
        except TimeoutError:
            return False
        return True

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

    def prepare(self, servo_id: int = 1, speed: int = 1000, acc: int = 50) -> None:
        self._write(servo_id, ADDR_ACC, bytes([acc]))
        self._write(
            servo_id,
            ADDR_GOAL_SPEED,
            bytes([speed & 0xFF, (speed >> 8) & 0xFF]),
        )
        self.enable_torque(servo_id, True)

    def move(
        self,
        position: int,
        servo_id: int = 1,
        speed: int = 1000,
        acc: int = 50,
    ) -> None:
        if not 0 <= position <= POSITION_MAX:
            raise ValueError(f"position must be 0–{POSITION_MAX}, got {position}")
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
        self.enable_torque(servo_id, True)

    def set_goal(self, position: int, servo_id: int = 1) -> None:
        self.set_goals({servo_id: position})

    def set_goals(self, goals: dict[int, int]) -> None:
        if not goals:
            return
        payload = bytearray([ADDR_GOAL_POSITION, 2])
        for servo_id, position in goals.items():
            if not 0 <= position <= POSITION_MAX:
                raise ValueError(f"position must be 0–{POSITION_MAX}, got {position}")
            payload.extend([servo_id, position & 0xFF, (position >> 8) & 0xFF])
        self._serial.write(_packet(BROADCAST_ID, INST_SYNC_WRITE, bytes(payload)))
        self._serial.flush()
        self._serial.reset_input_buffer()

    def position(self, servo_id: int = 1) -> int:
        data = self._read(servo_id, ADDR_PRESENT_POSITION, 2)
        return (data[0] | (data[1] << 8)) & POSITION_MAX
