"""Set a servo's travel limits explicitly, then sweep them slowly to verify."""

from __future__ import annotations

import argparse
import time

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

ARRIVE_TOLERANCE = 20
PAUSE = 1.0
SWEEP_CYCLES = 3


def _settle(bus: STS3215Bus, servo_id: int, goal: int, timeout: float = 20.0) -> int:
    bus.set_goal(goal, servo_id=servo_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.08)
        if abs(bus.position(servo_id=servo_id) - goal) <= ARRIVE_TOLERANCE:
            break
    return bus.position(servo_id=servo_id)


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
    parser.add_argument("--min", type=int, help="Anticlockwise limit, absolute.")
    parser.add_argument("--max", type=int, help="Clockwise limit, absolute.")
    parser.add_argument(
        "--travel",
        type=int,
        help="Symmetric limit in ticks either side of zero, instead of min/max.",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=300,
        help="Servo tracking speed. Lower is slower.",
    )
    parser.add_argument(
        "--cycles", type=int, default=SWEEP_CYCLES, help="Sweeps to run."
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Sweep without writing the limits to the output file.",
    )
    args = parser.parse_args()

    zero = args.zero
    if zero is None:
        record = read_records(args.output).get(str(args.id))
        if record is None:
            raise SystemExit(
                f"No zero for servo {args.id} in {args.output}. "
                "Run set_zero first, or pass --zero."
            )
        zero = int(record["zero"])

    if args.travel is not None:
        if args.min is not None or args.max is not None:
            raise SystemExit("Use --travel or --min/--max, not both.")
        if args.travel <= 0:
            raise SystemExit("--travel must be > 0")
        minimum, maximum = zero - args.travel, zero + args.travel
    else:
        if args.min is None or args.max is None:
            raise SystemExit("Pass --min and --max, or --travel.")
        minimum, maximum = args.min, args.max

    if not 0 <= minimum <= zero <= maximum <= POSITION_MAX:
        raise SystemExit(
            f"Need 0 <= min <= zero <= max <= {POSITION_MAX}, "
            f"got min={minimum} zero={zero} max={maximum}"
        )
    if args.cycles < 1:
        raise SystemExit("--cycles must be >= 1")

    print(f"Servo {args.id}: zero {zero}, limits {minimum} - {maximum}")
    print(
        f"  anticlockwise {zero - minimum} ticks "
        f"({degrees_from_ticks(zero - minimum):.1f} deg)"
    )
    print(
        f"  clockwise     {maximum - zero} ticks "
        f"({degrees_from_ticks(maximum - zero):.1f} deg)"
    )
    print(f"Sweeping {args.cycles}x at speed {args.speed}, pausing {PAUSE:g}s at each stop.\n")

    with STS3215Bus(args.port, args.baudrate) as bus:
        bus.prepare(servo_id=args.id, speed=args.speed, acc=20)

        print(f"centre {zero} -> at {_settle(bus, args.id, zero)}")
        time.sleep(PAUSE)

        for cycle in range(1, args.cycles + 1):
            for label, goal in (
                ("clockwise max", maximum),
                ("centre", zero),
                ("anticlockwise max", minimum),
                ("centre", zero),
            ):
                at = _settle(bus, args.id, goal)
                print(f"  cycle {cycle}: {label} {goal} -> at {at}")
                time.sleep(PAUSE)

        print(f"\nHolding at centre {bus.position(servo_id=args.id)}.")

    if args.no_save:
        print("Not saved (--no-save).")
    else:
        merge_record(args.output, args.id, zero, minimum, maximum)
        print(f"Wrote servo {args.id} to {args.output}: "
              f"zero={zero} min={minimum} max={maximum}")


if __name__ == "__main__":
    main()
