"""Write the calibrated travel limits into the servos' own EEPROM.

Clamping in Python only protects against this code. Writing addresses 9 and 11
makes the servo itself refuse goals outside the range, which still holds if a
process crashes mid-move, sends a bad value, or is replaced entirely.
"""

from __future__ import annotations

import argparse

from mio_core_services.firmware.servo_zeros_io import degrees_from_ticks
from mio_core_services.firmware.sts3215 import (
    ADDR_MAX_ANGLE_LIMIT,
    ADDR_MIN_ANGLE_LIMIT,
    ADDR_MODE,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    MODE_POSITION,
    POSITION_MAX,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import load_zeros


def read_limits(bus: STS3215Bus, servo_id: int) -> tuple[int, int, int]:
    return (
        bus.read_word(servo_id, ADDR_MIN_ANGLE_LIMIT),
        bus.read_word(servo_id, ADDR_MAX_ANGLE_LIMIT),
        bus.read_byte(servo_id, ADDR_MODE),
    )


def check(bus: STS3215Bus, servo_id: int, minimum: int, maximum: int) -> list[str]:
    """Return the reasons this servo's hardware limits do not match."""
    hw_min, hw_max, mode = read_limits(bus, servo_id)
    problems = []
    if mode != MODE_POSITION:
        problems.append(f"mode is {mode}, not position mode ({MODE_POSITION}); limits are ignored")
    if hw_min != minimum:
        problems.append(f"min limit is {hw_min}, expected {minimum}")
    if hw_max != maximum:
        problems.append(f"max limit is {hw_max}, expected {maximum}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-z", "--zeros", default="servo_zeros.json")
    parser.add_argument(
        "--id", type=int, action="append", dest="ids",
        help="Servo to write. Repeatable. Defaults to every servo in the file.",
    )
    parser.add_argument(
        "--verify", action="store_true", help="Only report; change nothing."
    )
    parser.add_argument(
        "--factory",
        action="store_true",
        help=f"Restore the full 0-{POSITION_MAX} travel instead.",
    )
    args = parser.parse_args()

    zeros = load_zeros(args.zeros)
    ids = args.ids or sorted(zeros)
    missing = [i for i in ids if i not in zeros]
    if missing:
        raise SystemExit(f"{args.zeros} has no entry for servo(s) {missing}")

    failures = 0
    with STS3215Bus(args.port, args.baudrate) as bus:
        for servo_id in ids:
            rng = zeros[servo_id]
            minimum, maximum = (0, POSITION_MAX) if args.factory else (rng.min, rng.max)

            if not args.factory and minimum == maximum:
                raise SystemExit(
                    f"servo {servo_id}: min and max are both {minimum}. "
                    "Recalibrate before writing hardware limits."
                )

            hw_min, hw_max, mode = read_limits(bus, servo_id)
            print(
                f"servo {servo_id}: hardware {hw_min}-{hw_max} (mode {mode}), "
                f"wanted {minimum}-{maximum}"
            )

            if args.verify:
                problems = check(bus, servo_id, minimum, maximum)
                if problems:
                    failures += 1
                    for problem in problems:
                        print(f"  MISMATCH: {problem}")
                else:
                    print("  OK")
                continue

            bus.write_config(
                servo_id,
                {
                    ADDR_MIN_ANGLE_LIMIT: (minimum, 2),
                    ADDR_MAX_ANGLE_LIMIT: (maximum, 2),
                },
            )
            problems = check(bus, servo_id, minimum, maximum)
            if problems:
                failures += 1
                for problem in problems:
                    print(f"  FAILED TO VERIFY: {problem}")
            else:
                span = degrees_from_ticks(maximum - minimum)
                print(f"  written and verified: {minimum}-{maximum} ({span:.1f} deg)")

    if failures:
        raise SystemExit(f"\n{failures} servo(s) did not verify.")
    print("\nAll servos verified." if not args.verify else "\nAll servos match.")


if __name__ == "__main__":
    main()
