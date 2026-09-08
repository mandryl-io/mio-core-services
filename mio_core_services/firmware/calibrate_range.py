"""Jog a servo to each travel limit in turn, then sweep the range to verify it."""

from __future__ import annotations

import argparse
import sys
import time

from mio_core_services.firmware.jog import jog_speed_for
from mio_core_services.firmware.servo_zeros_io import (
    degrees_from_ticks,
    merge_record,
    read_records,
)
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    POSITION_MAX,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import (
    CONFIRM_KEYS,
    HOLD_DT,
    JOG_DT,
    LEFT_KEYS,
    QUIT_KEYS,
    RIGHT_KEYS,
    RawTerminal,
)

ARRIVE_TOLERANCE = 20
PAUSE = 1.0
SWEEP_CYCLES = 3


def _say(message: str = "") -> None:
    sys.stdout.write(f"{message}\r\n")
    sys.stdout.flush()


def _settle(bus: STS3215Bus, servo_id: int, goal: int, timeout: float = 20.0) -> int:
    bus.set_goal(goal, servo_id=servo_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.08)
        if abs(bus.position(servo_id=servo_id) - goal) <= ARRIVE_TOLERANCE:
            break
    return bus.position(servo_id=servo_id)


def _jog(
    bus: STS3215Bus,
    terminal: RawTerminal,
    servo_id: int,
    start: int,
    zero: int,
    step: int,
) -> int:
    """Hold left/right to move, Enter to accept. Returns the chosen position."""
    position = start
    direction = 0
    last_hold = 0.0
    while True:
        key = terminal.poll_key(JOG_DT)
        now = time.monotonic()
        while key is not None:
            if key in LEFT_KEYS:
                direction, last_hold = -1, now
            elif key in RIGHT_KEYS:
                direction, last_hold = 1, now
            elif key in CONFIRM_KEYS:
                chosen = bus.position(servo_id=servo_id)
                sys.stdout.write("\r\x1b[K")
                return chosen
            elif key in QUIT_KEYS:
                raise SystemExit("\r\nAborted. Nothing was saved.\r")
            key = terminal.poll_key(0)
        if now - last_hold > HOLD_DT:
            direction = 0
            continue
        position = max(0, min(POSITION_MAX, position + direction * step))
        bus.set_goal(position, servo_id=servo_id)
        sys.stdout.write(
            f"\r\x1b[K  {position}   {degrees_from_ticks(position - zero):+.1f} deg from centre"
        )
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-o", "--output", default="servo_zeros.json")
    parser.add_argument(
        "--zero",
        type=int,
        help="Centre position. Defaults to the value in the output file.",
    )
    parser.add_argument("--step", type=int, default=4, help="Ticks per jog tick.")
    parser.add_argument(
        "--jog-speed",
        type=int,
        help="Tracking speed while jogging. Defaults to match the jog rate.",
    )
    parser.add_argument("--jog-acc", type=int, default=40)
    parser.add_argument(
        "--speed", type=int, default=300, help="Sweep speed. Lower is slower."
    )
    parser.add_argument("--cycles", type=int, default=SWEEP_CYCLES)
    parser.add_argument(
        "--keep-torque",
        action="store_true",
        dest="hold_torque",
        help="Leave torque engaged when this exits, instead of going limp.",
    )
    args = parser.parse_args()
    if args.step < 1:
        raise SystemExit("--step must be >= 1")
    if args.cycles < 1:
        raise SystemExit("--cycles must be >= 1")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY for arrow-key jogging. Run with: ssh -t ...")

    zero = args.zero
    if zero is None:
        record = read_records(args.output).get(str(args.id))
        if record is None:
            raise SystemExit(
                f"No zero for servo {args.id} in {args.output}. "
                "Run set_zero first, or pass --zero."
            )
        zero = int(record["zero"])

    print(f"Servo {args.id}: centre is {zero}.")
    print("Hold left/right to jog, Enter to confirm, q to abort.\n")

    release_ids = () if args.hold_torque else [args.id]
    with STS3215Bus(args.port, args.baudrate, release_ids=release_ids) as bus:
        jog_speed = args.jog_speed or jog_speed_for(args.step)
        bus.prepare(servo_id=args.id, speed=jog_speed, acc=args.jog_acc)

        with RawTerminal() as terminal:
            _say(f"Centring at {_settle(bus, args.id, zero)}...")
            _say()

            _say("1. Jog to the LEFT limit, then press Enter.")
            left = _jog(bus, terminal, args.id, zero, zero, args.step)
            _say(f"   left limit {left}  ({degrees_from_ticks(left - zero):+.1f} deg)")
            _say()

            _say("Back to centre...")
            _settle(bus, args.id, zero)
            _say()

            _say("2. Jog to the RIGHT limit, then press Enter.")
            right = _jog(bus, terminal, args.id, zero, zero, args.step)
            _say(f"   right limit {right}  ({degrees_from_ticks(right - zero):+.1f} deg)")
            _say()

            minimum, maximum = min(left, right), max(left, right)
            if minimum == maximum:
                raise SystemExit("\r\nBoth limits are the same; nothing to sweep.\r")
            if not minimum <= zero <= maximum:
                raise SystemExit(
                    f"\r\nCentre {zero} is not between the limits "
                    f"{minimum} and {maximum}.\r"
                )

            _say(f"Range {minimum} - {maximum}, centre {zero}.")
            _say(f"Sweeping {args.cycles}x, pausing {PAUSE:g}s at every stop.")
            _say()

            bus.prepare(servo_id=args.id, speed=args.speed, acc=20)
            _settle(bus, args.id, zero)
            time.sleep(PAUSE)
            for cycle in range(1, args.cycles + 1):
                for label, goal in (
                    ("right", maximum),
                    ("centre", zero),
                    ("left", minimum),
                    ("centre", zero),
                ):
                    at = _settle(bus, args.id, goal)
                    _say(f"  cycle {cycle}: {label} {goal} -> at {at}")
                    time.sleep(PAUSE)
            _say()
            _say("Holding at centre." if args.hold_torque else "At centre.")

        merge_record(args.output, args.id, zero, minimum, maximum)
        print(f"Wrote servo {args.id} to {args.output}: "
              f"zero={zero} min={minimum} max={maximum}")


if __name__ == "__main__":
    main()
