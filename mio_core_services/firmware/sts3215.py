"""Minimal STS3215 (Feetech SMS/STS) helper: enable torque, move, and read."""

from __future__ import annotations

import time
from collections.abc import Sequence

import serial

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
INST_SYNC_WRITE = 0x83
ADDR_ID = 5
# Position-loop tuning. All EEPROM: torque off and unlock before writing.
ADDR_P_COEFFICIENT = 21
ADDR_D_COEFFICIENT = 22
ADDR_I_COEFFICIENT = 23
ADDR_MIN_STARTUP_FORCE = 24  # two bytes
ADDR_CW_DEAD_ZONE = 26
ADDR_CCW_DEAD_ZONE = 27
ADDR_TORQUE_ENABLE = 40
ADDR_ACC = 41
ADDR_GOAL_POSITION = 42
ADDR_GOAL_SPEED = 46
ADDR_LOCK = 55
ADDR_PRESENT_POSITION = 56

# Waveshare Bus Servo Driver HAT (A) in ESP32 transparent-transmission
# mode: the Pi drives GPIO 14/15 at 115200 and the ESP32 forwards to the
# servo bus at 1 Mbps. See docs/waveshare-servo-hat.md.
DEFAULT_PORT = "/dev/ttyAMA0"
DEFAULT_BAUDRATE = 115_200
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
        release_ids: Sequence[int] | None = None,
    ) -> None:
        # Servos to limp on close. A servo holding a position it can already
        # support mechanically only buzzes correcting its own noise.
        self._release_ids = tuple(release_ids or ())
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
        for servo_id in self._release_ids:
            try:
                self.enable_torque(servo_id, False)
            except (TimeoutError, OSError, serial.SerialException):
                pass
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
        # Voltage warning (error=0x01) makes INST_PING's reply identical to TX.
        try:
            return self._read(servo_id, ADDR_ID, 1)[0] == servo_id
        except TimeoutError:
            return False

    def set_id(self, new_id: int, current_id: int = BROADCAST_ID) -> None:
        if not 1 <= new_id <= 253:
            raise ValueError(f"new_id must be 1–253, got {new_id}")
        if current_id != BROADCAST_ID and not 1 <= current_id <= 253:
            raise ValueError(f"current_id must be 1–253 or {BROADCAST_ID}, got {current_id}")
        self.enable_torque(current_id, False)
        time.sleep(0.02)
        self._write(current_id, ADDR_LOCK, bytes([0]))
        time.sleep(0.05)
        self._write(current_id, ADDR_ID, bytes([new_id]))
        # ACK comes from the new ID; EEPROM needs a moment before it replies.
        time.sleep(0.15)
        self._write(new_id, ADDR_LOCK, bytes([1]))

    def read_byte(self, servo_id: int, address: int) -> int:
        return self._read(servo_id, address, 1)[0]

    def read_word(self, servo_id: int, address: int) -> int:
        data = self._read(servo_id, address, 2)
        return data[0] | (data[1] << 8)

    def write_config(self, servo_id: int, values: dict[int, tuple[int, int]]) -> None:
        """Write EEPROM tuning registers as {address: (value, byte_width)}.

        EEPROM only accepts writes with torque off and the lock released, so
        this brackets the writes with both.
        """
        if not values:
            return
        self.enable_torque(servo_id, False)
        time.sleep(0.02)
        self._write(servo_id, ADDR_LOCK, bytes([0]))
        time.sleep(0.05)
        for address, (value, width) in sorted(values.items()):
            if width == 1:
                payload = bytes([value & 0xFF])
            else:
                payload = bytes([value & 0xFF, (value >> 8) & 0xFF])
            self._write(servo_id, address, payload)
            time.sleep(0.05)
        self._write(servo_id, ADDR_LOCK, bytes([1]))
        time.sleep(0.05)

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
        # Block-writing ACC..SPEED (with time=0) updates goal but does not move.
        self.enable_torque(servo_id, True)
        self._write(servo_id, ADDR_ACC, bytes([acc]))
        self._write(
            servo_id,
            ADDR_GOAL_SPEED,
            bytes([speed & 0xFF, (speed >> 8) & 0xFF]),
        )
        self.set_goal(position, servo_id=servo_id)

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
