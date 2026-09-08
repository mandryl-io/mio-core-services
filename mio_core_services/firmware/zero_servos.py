"""Teleop each STS3215 to its physical zero, record ± travel, and write JSON."""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Self

from mio_core_services.firmware import jog
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    POSITION_MAX,
    STS3215Bus,
)

LEFT_KEYS = frozenset({"\x1b[D", "\x1bOD", "a", "h"})
RIGHT_KEYS = frozenset({"\x1b[C", "\x1bOC", "d", "l"})
CONFIRM_KEYS = frozenset({"\r", "\n"})
QUIT_KEYS = frozenset({"q", "\x03"})
JOG_DT = jog.JOG_DT
HOLD_DT = jog.HOLD_DT


@dataclass(frozen=True)
class ServoRange:
    zero: int
    min: int = 0
    max: int = POSITION_MAX


def _parse_position(value: object, label: str) -> int:
    try:
        position = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{label}: invalid position {value!r}") from exc
    if not 0 <= position <= POSITION_MAX:
        raise SystemExit(f"{label}: position must be 0–{POSITION_MAX}, got {position}")
    return position


def load_zeros(path: str) -> dict[int, ServoRange]:
    try:
        with open(path) as handle:
            raw = json.load(handle)
    except OSError as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise SystemExit(f"{path} must be a non-empty JSON object of id -> zero/limits")
    zeros: dict[int, ServoRange] = {}
    for key, value in raw.items():
        try:
            servo_id = int(key)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"{path}: invalid servo id {key!r}") from exc
        if isinstance(value, dict):
            if "zero" not in value:
                raise SystemExit(f"{path}: servo {servo_id} missing 'zero'")
            zero = _parse_position(value["zero"], f"{path}: servo {servo_id} zero")
            lo = _parse_position(value.get("min", 0), f"{path}: servo {servo_id} min")
            hi = _parse_position(
                value.get("max", POSITION_MAX), f"{path}: servo {servo_id} max"
            )
        else:
            zero = _parse_position(value, f"{path}: servo {servo_id}")
            lo, hi = 0, POSITION_MAX
        if not lo <= zero <= hi:
            raise SystemExit(
                f"{path}: servo {servo_id} zero {zero} is outside min–max {lo}–{hi}"
            )
        zeros[servo_id] = ServoRange(zero=zero, min=lo, max=hi)
    return zeros


class RawTerminal:
    def __enter__(self) -> Self:
        self.old = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        return self

    def __exit__(self, *args: object) -> None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old)

    def read_key(self) -> str:
        fd = sys.stdin.fileno()
        ch = os.read(fd, 1)
        if ch != b"\x1b":
            return ch.decode("latin1")
        seq = ch
        while len(seq) < 3 and select.select([fd], [], [], 0.05)[0]:
            seq += os.read(fd, 1)
        return seq.decode("latin1")

    def poll_key(self, timeout: float) -> str | None:
        if not select.select([sys.stdin.fileno()], [], [], timeout)[0]:
            return None
        return self.read_key()


def _status(message: str) -> None:
    sys.stdout.write(f"\r\x1b[K{message}")
    sys.stdout.flush()


def _read_position(bus: STS3215Bus, servo_id: int, port: str) -> int:
    try:
        return bus.position(servo_id=servo_id)
    except TimeoutError:
        raise SystemExit(
            f"No reply from servo {servo_id} on {port}. "
            "Check external power and the servo ID. For a Waveshare HAT (A) "
            "on /dev/serial0, use ESP32 transparent-transmission mode at 115200 baud."
        )


def _parse_offset(token: str) -> int:
    token = token.strip().replace("±", "").lstrip("+")
    if token.startswith("-"):
        token = token[1:]
    value = int(token)
    if value < 0:
        raise ValueError("travel must be >= 0")
    return value


def _limits_from_travel(zero: int, text: str) -> tuple[int, int]:
    text = text.strip().replace(" ", "")
    if not text:
        return 0, POSITION_MAX
    if "/" in text:
        left, right = text.split("/", 1)
        plus, minus = _parse_offset(left), _parse_offset(right)
    else:
        plus = minus = _parse_offset(text)
    lo = max(0, zero - minus)
    hi = min(POSITION_MAX, zero + plus)
    if lo > hi:
        raise ValueError(f"limits invert: min {lo} > max {hi}")
    return lo, hi


def _prompt_limits(zero: int) -> tuple[int, int]:
    prompt = "± travel from zero in ticks (300 or +400/-200, empty = no extra limit): "
    while True:
        try:
            text = input(prompt)
        except EOFError:
            return 0, POSITION_MAX
        try:
            lo, hi = _limits_from_travel(zero, text)
        except ValueError as exc:
            print(f"Invalid travel: {exc}")
            continue
        print(f"limits {lo}–{hi}")
        return lo, hi


def _teleop_until_zero(
    bus: STS3215Bus,
    terminal: RawTerminal,
    servo_id: int,
    port: str,
    step: int,
    speed: int,
) -> int | None:
    position = _read_position(bus, servo_id, port)
    bus.prepare(servo_id=servo_id, speed=speed, acc=50)
    bus.set_goal(position, servo_id=servo_id)
    sys.stdout.write(
        f"Servo {servo_id}: hold left/right to jog, Enter to record zero, q quits.\r\n"
    )
    sys.stdout.flush()
    direction = 0
    last_hold = 0.0
    while True:
        key = terminal.poll_key(JOG_DT)
        now = time.monotonic()
        confirmed = False
        quit_requested = False
        while key is not None:
            if key in LEFT_KEYS:
                direction = -1
                last_hold = now
            elif key in RIGHT_KEYS:
                direction = 1
                last_hold = now
            elif key in CONFIRM_KEYS:
                confirmed = True
                break
            elif key in QUIT_KEYS:
                quit_requested = True
                break
            key = terminal.poll_key(0)
        if quit_requested:
            return None
        if confirmed:
            actual = _read_position(bus, servo_id, port)
            sys.stdout.write(f"\r\x1b[KServo {servo_id} zero = {actual}\r\n")
            sys.stdout.flush()
            return actual
        if now - last_hold > HOLD_DT:
            direction = 0
            continue
        position = max(0, min(POSITION_MAX, position + direction * step))
        bus.set_goal(position, servo_id=servo_id)
        _status(f"servo {servo_id} -> {position}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ids",
        nargs="+",
        type=int,
        metavar="ID",
        help="Servo IDs to zero, in order.",
    )
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument(
        "-o",
        "--output",
        default="servo_zeros.json",
        help="JSON file to write recorded zero positions and min/max limits.",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=5,
        help="Ticks added per jog tick while a key is held (4096 = 360°).",
    )
    parser.add_argument(
        "--speed",
        type=int,
        help="Tracking speed. Defaults to match the jog rate, which is what "
        "keeps jogging smooth.",
    )
    args = parser.parse_args()
    if args.step < 1:
        raise SystemExit("--step must be >= 1")
    if len(args.ids) != len(set(args.ids)):
        raise SystemExit("Servo IDs must be unique.")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY for arrow-key teleop.")

    speed = args.speed or jog.jog_speed_for(args.step)

    records: dict[str, dict[str, int]] = {}
    with STS3215Bus(args.port, args.baudrate) as bus:
        for servo_id in args.ids:
            with RawTerminal() as terminal:
                recorded = _teleop_until_zero(
                    bus,
                    terminal,
                    servo_id,
                    args.port,
                    args.step,
                    speed,
                )
            if recorded is None:
                sys.stdout.write("Stopped.\n")
                break
            lo, hi = _prompt_limits(recorded)
            records[str(servo_id)] = {"zero": recorded, "min": lo, "max": hi}

    if not records:
        raise SystemExit("No zeros recorded.")

    with open(args.output, "w") as handle:
        json.dump(records, handle, indent=2)
        handle.write("\n")
    sys.stdout.write(f"Wrote {len(records)} servo(s) to {args.output}\n")


if __name__ == "__main__":
    main()
