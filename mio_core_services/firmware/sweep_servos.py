"""Move each STS3215 in a zeros JSON through its full range, then back to zero."""

from __future__ import annotations

import argparse
import sys
import time

from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import load_zeros

ARRIVE_TOLERANCE = 40


def _wait_until(
    bus: STS3215Bus,
    servo_id: int,
    goal: int,
    timeout: float,
) -> int:
    deadline = time.monotonic() + timeout
    last: int | None = None
    while time.monotonic() < deadline:
        try:
            last = bus.position(servo_id=servo_id)
        except TimeoutError:
            time.sleep(0.05)
            continue
        if abs(last - goal) <= ARRIVE_TOLERANCE:
            return last
        time.sleep(0.05)
    raise SystemExit(
        f"Servo {servo_id} did not reach {goal} "
        f"(last={last}) within {timeout:.1f}s"
    )


def _goto(
    bus: STS3215Bus,
    servo_id: int,
    goal: int,
    timeout: float,
    hold: float,
    label: str,
) -> None:
    print(f"  {label} {goal}")
    bus.set_goal(goal, servo_id=servo_id)
    _wait_until(bus, servo_id, goal, timeout)
    if hold > 0:
        time.sleep(hold)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "zeros",
        help="JSON file of servo id -> zero/min/max. Each servo is swept min→max→zero.",
    )
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument(
        "--speed",
        type=int,
        default=1000,
        help="How fast each servo tracks its sweep goals.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for each waypoint before giving up.",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=0.4,
        help="Seconds to pause at min, max, and zero.",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be > 0")
    if args.hold < 0:
        raise SystemExit("--hold must be >= 0")

    zeros = load_zeros(args.zeros)
    print(f"Sweeping {len(zeros)} servo(s) from {args.zeros} on {args.port}")

    with STS3215Bus(args.port, args.baudrate) as bus:
        home = {servo_id: rng.zero for servo_id, rng in zeros.items()}
        for servo_id in zeros:
            bus.prepare(servo_id=servo_id, speed=args.speed, acc=50)
        print("Homing all to zero")
        bus.set_goals(home)
        for servo_id, rng in zeros.items():
            _wait_until(bus, servo_id, rng.zero, args.timeout)

        try:
            for servo_id, rng in zeros.items():
                print(
                    f"Servo {servo_id}: min {rng.min} → max {rng.max} → zero {rng.zero}"
                )
                _goto(bus, servo_id, rng.min, args.timeout, args.hold, "min")
                _goto(bus, servo_id, rng.max, args.timeout, args.hold, "max")
                _goto(bus, servo_id, rng.zero, args.timeout, args.hold, "zero")
        except KeyboardInterrupt:
            print("\nInterrupted; homing all to zero", file=sys.stderr)
            bus.set_goals(home)
            raise SystemExit(130) from None

    print("Done.")


if __name__ == "__main__":
    main()
