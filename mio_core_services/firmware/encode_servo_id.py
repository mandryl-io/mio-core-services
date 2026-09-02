"""Assign a unique ID to one STS3215. Connect only that servo to the bus."""

import argparse
import time

from mio_core_services.firmware.sts3215 import (
    BROADCAST_ID,
    DEFAULT_PORT,
    STS3215Bus,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--new-id", type=int, required=True)
    parser.add_argument(
        "--current-id",
        type=int,
        default=BROADCAST_ID,
        help="Current ID. Default 254 (broadcast) — only one servo on the bus.",
    )
    args = parser.parse_args()

    print(f"Encoding servo {args.current_id} -> {args.new_id} on {args.port}")
    with STS3215Bus(args.port) as bus:
        bus.set_id(args.new_id, current_id=args.current_id)
        time.sleep(0.05)
        if not bus.ping(args.new_id):
            raise SystemExit(
                f"Wrote ID {args.new_id} but ping failed. "
                "Check external power, jumper B, and that only one servo is connected."
            )
    print(f"Servo now responds as ID {args.new_id}")


if __name__ == "__main__":
    main()
