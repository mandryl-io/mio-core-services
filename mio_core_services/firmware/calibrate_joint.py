"""Guided calibration for one joint: centre, fit the part, set zero and limits."""

from __future__ import annotations

import argparse
import sys
import time

from mio_core_services.firmware.servo_zeros_io import (
    degrees_from_ticks,
    merge_record,
    read_records,
)
from mio_core_services.firmware.sts3215 import (
    CENTER_POSITION,
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

UP_KEYS = frozenset({"\x1b[A", "\x1bOA", "w", "k"})
DOWN_KEYS = frozenset({"\x1b[B", "\x1bOB", "s", "j"})

# Which keys jog which way, and what the two limits are called.
KEY_MODES = {
    "left-right": (RIGHT_KEYS, LEFT_KEYS, "left/right", "right", "left"),
    "up-down": (UP_KEYS, DOWN_KEYS, "up/down", "up", "down"),
}

ARRIVE_TOLERANCE = 20
PAUSE = 1.0
# Goals are re-issued every JOG_DT, so the servo must still be travelling when
# the next one lands. Commanding much faster than the jog rate makes it sprint,
# stop, and wait, which reads as jitter.
JOG_SPEED_HEADROOM = 1.25
MIN_JOG_SPEED = 50


def jog_speed_for(step: int) -> int:
    """Tracking speed matched to how fast jogging actually advances the goal."""
    return max(MIN_JOG_SPEED, round(step / JOG_DT * JOG_SPEED_HEADROOM))


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


def _wait_for_enter(terminal: RawTerminal) -> None:
    while True:
        key = terminal.poll_key(0.1)
        if key is None:
            continue
        if key in QUIT_KEYS:
            raise SystemExit("\r\nAborted. Nothing was saved.\r")
        if key in CONFIRM_KEYS:
            return


def _jog(
    bus: STS3215Bus,
    terminal: RawTerminal,
    servo_id: int,
    start: int,
    reference: int,
    step: int,
    plus_keys: frozenset[str],
    minus_keys: frozenset[str],
) -> int:
    position = start
    direction = 0
    last_hold = 0.0
    while True:
        key = terminal.poll_key(JOG_DT)
        now = time.monotonic()
        while key is not None:
            if key in plus_keys:
                direction, last_hold = 1, now
            elif key in minus_keys:
                direction, last_hold = -1, now
            elif key in CONFIRM_KEYS:
                sys.stdout.write("\r\x1b[K")
                sys.stdout.flush()
                return bus.position(servo_id=servo_id)
            elif key in QUIT_KEYS:
                raise SystemExit("\r\nAborted. Nothing was saved.\r")
            key = terminal.poll_key(0)
        if now - last_hold > HOLD_DT:
            direction = 0
            continue
        position = max(0, min(POSITION_MAX, position + direction * step))
        bus.set_goal(position, servo_id=servo_id)
        sys.stdout.write(
            f"\r\x1b[K  {position}   "
            f"{degrees_from_ticks(position - reference):+.1f} deg"
        )
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, required=True, help="Joint to calibrate.")
    parser.add_argument(
        "--keys",
        choices=sorted(KEY_MODES),
        default="left-right",
        help="Which arrow keys jog this joint.",
    )
    parser.add_argument(
        "--hold",
        type=int,
        action="append",
        dest="holds",
        help="Servo to drive to its recorded zero and hold. Repeatable. "
        "Defaults to every other servo in the file.",
    )
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-o", "--output", default="servo_zeros.json")
    parser.add_argument(
        "--centre",
        type=int,
        default=CENTER_POSITION,
        help="Where to park the shaft while the part is fitted.",
    )
    parser.add_argument(
        "--skip-prove",
        action="store_true",
        help="Park at the centre without the full-travel swing first.",
    )
    parser.add_argument("--step", type=int, default=4, help="Ticks per jog tick.")
    parser.add_argument("--jog-speed", type=int, default=800)
    parser.add_argument("--speed", type=int, default=300, help="Sweep speed.")
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()
    if args.step < 1:
        raise SystemExit("--step must be >= 1")
    if not 0 <= args.centre <= POSITION_MAX:
        raise SystemExit(f"--centre must be 0-{POSITION_MAX}")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY for arrow-key jogging. Run with: ssh -t ...")

    plus_keys, minus_keys, key_label, plus_name, minus_name = KEY_MODES[args.keys]
    jog_speed = args.jog_speed or jog_speed_for(args.step)

    records = read_records(args.output)
    holds = args.holds
    if holds is None:
        holds = [int(key) for key in records if int(key) != args.id]
    missing = [servo_id for servo_id in holds if str(servo_id) not in records]
    if missing:
        raise SystemExit(f"{args.output} has no zero for servo(s) {missing} to hold")

    print(f"Calibrating servo {args.id}. Jog with {key_label}, Enter to confirm, q to abort.\n")

    with STS3215Bus(args.port, args.baudrate) as bus:
        for servo_id in holds:
            zero = int(records[str(servo_id)]["zero"])
            bus.prepare(servo_id=servo_id, speed=args.speed, acc=20)
            print(f"Holding servo {servo_id} at its zero {zero} -> "
                  f"at {_settle(bus, servo_id, zero)}")

        bus.prepare(servo_id=args.id, speed=args.travel_speed, acc=30)
        if args.skip_prove:
            parked = _settle(bus, args.id, args.centre)
        else:
            # Swing the bare shaft end to end so the centre is visibly halfway.
            print(f"Proving servo {args.id}: full travel both ways, then centre.")
            for label, goal in (("one end", 0), ("other end", POSITION_MAX)):
                print(f"  {label} {goal} -> at {_settle(bus, args.id, goal)}")
                time.sleep(0.4)
            parked = _settle(bus, args.id, args.centre)
            print(f"  centre {args.centre} -> at {parked}")
        print(f"Servo {args.id} parked at {parked} (torque on).")
        print(f"Jogging at speed {jog_speed}, acc {args.jog_acc}, step {args.step}.\n")

        with RawTerminal() as terminal:
            _say("1. Fit the part now. Press Enter when it is on, or q to abort.")
            _wait_for_enter(terminal)
            _say()

            _say(f"2. Jog to the joint's true centre ({key_label}), then Enter.")
            bus.prepare(servo_id=args.id, speed=jog_speed, acc=args.jog_acc)
            zero = _jog(
                bus, terminal, args.id, parked, args.centre,
                args.step, plus_keys, minus_keys,
            )
            _say(f"   zero {zero}  ({degrees_from_ticks(zero - args.centre):+.1f} deg "
                 "from the shaft centre)")
            _say()

            _say(f"3. Jog to maximum {plus_name}, then Enter.")
            bus.prepare(servo_id=args.id, speed=jog_speed, acc=args.jog_acc)
            first = _jog(
                bus, terminal, args.id, zero, zero,
                args.step, plus_keys, minus_keys,
            )
            _say(f"   max {plus_name} {first}  "
                 f"({degrees_from_ticks(first - zero):+.1f} deg)")
            _say()

            _say("Back to centre...")
            bus.prepare(servo_id=args.id, speed=args.travel_speed, acc=30)
            _settle(bus, args.id, zero)
            _say()

            _say(f"4. Jog to maximum {minus_name}, then Enter.")
            bus.prepare(servo_id=args.id, speed=jog_speed, acc=args.jog_acc)
            second = _jog(
                bus, terminal, args.id, zero, zero,
                args.step, plus_keys, minus_keys,
            )
            _say(f"   max {minus_name} {second}  "
                 f"({degrees_from_ticks(second - zero):+.1f} deg)")
            _say()

            minimum, maximum = min(first, second), max(first, second)
            if minimum == maximum:
                raise SystemExit("\r\nBoth limits are the same; nothing to sweep.\r")
            if not minimum <= zero <= maximum:
                raise SystemExit(
                    f"\r\nZero {zero} is not between the limits "
                    f"{minimum} and {maximum}.\r"
                )

            _say(f"5. Sweeping {args.cycles}x, pausing {PAUSE:g}s at each stop.")
            bus.prepare(servo_id=args.id, speed=args.speed, acc=20)
            _settle(bus, args.id, zero)
            time.sleep(PAUSE)
            for cycle in range(1, args.cycles + 1):
                for label, goal in (
                    (f"max {plus_name}", maximum),
                    ("centre", zero),
                    (f"max {minus_name}", minimum),
                    ("centre", zero),
                ):
                    at = _settle(bus, args.id, goal)
                    _say(f"   cycle {cycle}: {label} {goal} -> at {at}")
                    time.sleep(PAUSE)
            _say()
            _say("Holding at centre.")

        merge_record(args.output, args.id, zero, minimum, maximum)
        print(f"Wrote servo {args.id} to {args.output}: "
              f"zero={zero} min={minimum} max={maximum}")


if __name__ == "__main__":
    main()
