"""Record a servo's current position as its zero, the default start position."""

import argparse

from mio_core_services.firmware.servo_zeros_io import merge_record, read_records
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    POSITION_MAX,
    STS3215Bus,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=1, help="Servo to record.")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-o", "--output", default="servo_zeros.json")
    parser.add_argument(
        "--position",
        type=int,
        help="Record this position instead of reading the servo.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Release torque once the zero is saved.",
    )
    args = parser.parse_args()

    with STS3215Bus(args.port, args.baudrate) as bus:
        if args.position is not None:
            if not 0 <= args.position <= POSITION_MAX:
                raise SystemExit(f"--position must be 0-{POSITION_MAX}")
            zero = args.position
        else:
            try:
                zero = bus.position(servo_id=args.id)
            except TimeoutError as exc:
                raise SystemExit(
                    f"No reply from servo {args.id} on {args.port}: {exc}"
                ) from exc

        # Keep any limits already recorded, as long as they still bracket zero.
        existing = read_records(args.output).get(str(args.id), {})
        minimum = existing.get("min", 0)
        maximum = existing.get("max", POSITION_MAX)
        if not minimum <= zero <= maximum:
            print(
                f"Existing limits {minimum}-{maximum} do not contain {zero}; "
                "resetting them to the full range."
            )
            minimum, maximum = 0, POSITION_MAX

        merge_record(args.output, args.id, zero, minimum, maximum)
        print(f"Servo {args.id} zero = {zero} (limits {minimum}-{maximum})")
        print(f"Wrote {args.output}")

        if args.release:
            bus.enable_torque(args.id, False)
            print("Torque released.")


if __name__ == "__main__":
    main()
