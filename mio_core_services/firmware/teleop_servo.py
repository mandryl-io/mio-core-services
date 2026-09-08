"""Jog one STS3215 servo with held left/right arrow keys."""

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
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument(
        "--zeros",
        help="JSON file of servo id -> position. Resets --id to that position before teleop.",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=900,
        help="Jog velocity in ticks/s while a key is held (4096 = 360°).",
    )
    parser.add_argument(
        "--acc",
        type=int,
        default=60,
        help="Acceleration. Higher stops more crisply with less overshoot.",
    )
    parser.add_argument(
        "--stiff",
        action="store_true",
        help="Keep torque on while stopped. Off by default, because a servo "
        "holding a load the mechanism already supports only hunts.",
    )
    parser.add_argument(
        "--limp-after",
        type=float,
        default=0.4,
        help="Seconds of stillness before torque is cut.",
    )
    parser.add_argument(
        "--invert-x",
        action="store_true",
        help="Swap which way left/right drives.",
    )
    parser.add_argument(
        "--keep-torque",
        action="store_true",
        dest="hold_torque",
        help="Leave torque engaged when this exits, instead of going limp.",
    )
    args = parser.parse_args()
    if args.speed < 1:
        raise SystemExit("--speed must be >= 1")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY for arrow-key teleop.")

    release_ids = () if args.hold_torque else [args.id]
    with STS3215Bus(args.port, args.baudrate, release_ids=release_ids) as bus:
        if args.zeros:
            zeros = load_zeros(args.zeros)
            if args.id not in zeros:
                raise SystemExit(f"Servo {args.id} not in {args.zeros}")
            position = zeros[args.id].zero
        else:
            try:
                position = bus.position(servo_id=args.id)
            except TimeoutError as exc:
                raise SystemExit(str(exc)) from exc
        minimum, maximum = 0, POSITION_MAX
        if args.zeros:
            minimum, maximum = zeros[args.id].min, zeros[args.id].max
        driver = jog.VelocityJog(
            bus,
            args.id,
            minimum,
            maximum,
            args.speed,
            acc=args.acc,
            limp_after=None if args.stiff else args.limp_after,
        )
        bus.set_goal(position, servo_id=args.id)
        sys.stdout.write(
            f"Teleop servo {args.id} on {args.port} from {position}. "
            f"Hold left/right to jog at {args.speed} ticks/s, q quits.\r\n"
        )
        sys.stdout.flush()
        x_sign = -1 if args.invert_x else 1
        direction = 0
        last_hold = 0.0
        last_report = 0.0
        with RawTerminal() as terminal:
            while True:
                key = terminal.poll_key(JOG_DT)
                now = time.monotonic()
                done = key in QUIT_KEYS
                while key is not None and not done:
                    if key in LEFT_KEYS:
                        direction = -x_sign
                        last_hold = now
                    elif key in RIGHT_KEYS:
                        direction = x_sign
                        last_hold = now
                    elif key in QUIT_KEYS:
                        done = True
                        break
                    key = terminal.poll_key(0)
                if done:
                    break
                if now - last_hold > HOLD_DT:
                    direction = 0
                driver.steer(direction)
                driver.tick(now)
                if now - last_report > 0.1:
                    last_report = now
                    _status(f"servo {args.id} -> {driver.read()}")

    sys.stdout.write("\r\nDone.\r\n")


if __name__ == "__main__":
    main()
