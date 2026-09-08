"""Jog two STS3215 servos: left/right for one id, up/down for another."""

from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
import tty

from mio_core_services.firmware import jog
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    POSITION_MAX,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import load_zeros

LEFT_KEYS = frozenset({"\x1b[D", "\x1bOD", "a", "h"})
RIGHT_KEYS = frozenset({"\x1b[C", "\x1bOC", "d", "l"})
UP_KEYS = frozenset({"\x1b[A", "\x1bOA", "w", "k"})
DOWN_KEYS = frozenset({"\x1b[B", "\x1bOB", "s", "j"})
QUIT_KEYS = frozenset({"q", "\x03"})
JOG_DT = jog.JOG_DT
HOLD_DT = jog.HOLD_DT


class RawTerminal:
    def __enter__(self) -> RawTerminal:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument(
        "--id-1",
        type=int,
        default=1,
        help="Servo id jogged with left/right (or a/d, h/l).",
    )
    parser.add_argument(
        "--id-2",
        type=int,
        default=2,
        help="Servo id jogged with up/down (or w/s, k/j).",
    )
    parser.add_argument(
        "--zeros",
        help="JSON file of servo id -> zero/min/max. Resets --id-1/--id-2 and clamps jog to limits.",
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
        help="Tracking speed. Defaults to match the jog rate, which is "
        "what keeps jogging smooth.",
    )
    parser.add_argument(
        "--keep-torque",
        action="store_true",
        dest="hold_torque",
        help="Leave torque engaged when this exits, instead of going limp.",
    )
    args = parser.parse_args()
    if args.step < 1:
        raise SystemExit("--step must be >= 1")
    speed = args.speed or jog.jog_speed_for(args.step)
    if args.id_1 == args.id_2:
        raise SystemExit("--id-1 and --id-2 must be different")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY for arrow-key teleop.")

    release_ids = () if args.hold_torque else [args.id_1, args.id_2]
    with STS3215Bus(args.port, args.baudrate, release_ids=release_ids) as bus:
        min_1, max_1 = 0, POSITION_MAX
        min_2, max_2 = 0, POSITION_MAX
        if args.zeros:
            zeros = load_zeros(args.zeros)
            for servo_id in (args.id_1, args.id_2):
                if servo_id not in zeros:
                    raise SystemExit(f"Servo {servo_id} not in {args.zeros}")
            range_1 = zeros[args.id_1]
            range_2 = zeros[args.id_2]
            position_1 = range_1.zero
            position_2 = range_2.zero
            min_1, max_1 = range_1.min, range_1.max
            min_2, max_2 = range_2.min, range_2.max
        else:
            try:
                position_1 = bus.position(servo_id=args.id_1)
                position_2 = bus.position(servo_id=args.id_2)
            except TimeoutError as exc:
                raise SystemExit(str(exc)) from exc
        bus.prepare(servo_id=args.id_1, speed=speed, acc=50)
        bus.prepare(servo_id=args.id_2, speed=speed, acc=50)
        bus.set_goals({args.id_1: position_1, args.id_2: position_2})
        sys.stdout.write(
            f"Teleop servos {args.id_1}/{args.id_2} on {args.port} "
            f"from {position_1}/{position_2} "
            f"(limits {min_1}–{max_1}/{min_2}–{max_2}). "
            "Hold left/right and up/down to jog, q quits.\r\n"
        )
        sys.stdout.flush()
        direction_h = 0
        direction_v = 0
        last_hold_h = 0.0
        last_hold_v = 0.0
        with RawTerminal() as terminal:
            while True:
                key = terminal.poll_key(JOG_DT)
                now = time.monotonic()
                done = key in QUIT_KEYS
                while key is not None and not done:
                    if key in LEFT_KEYS:
                        direction_h = -1
                        last_hold_h = now
                    elif key in RIGHT_KEYS:
                        direction_h = 1
                        last_hold_h = now
                    elif key in DOWN_KEYS:
                        direction_v = -1
                        last_hold_v = now
                    elif key in UP_KEYS:
                        direction_v = 1
                        last_hold_v = now
                    elif key in QUIT_KEYS:
                        done = True
                        break
                    key = terminal.poll_key(0)
                if done:
                    break
                if now - last_hold_h > HOLD_DT:
                    direction_h = 0
                if now - last_hold_v > HOLD_DT:
                    direction_v = 0
                if direction_h == 0 and direction_v == 0:
                    continue
                if direction_h:
                    position_1 = max(
                        min_1, min(max_1, position_1 + direction_h * args.step)
                    )
                if direction_v:
                    position_2 = max(
                        min_2, min(max_2, position_2 + direction_v * args.step)
                    )
                bus.set_goals({args.id_1: position_1, args.id_2: position_2})
                _status(
                    f"servo {args.id_1} -> {position_1}  "
                    f"servo {args.id_2} -> {position_2}"
                )

    sys.stdout.write("\r\nDone.\r\n")


if __name__ == "__main__":
    main()
