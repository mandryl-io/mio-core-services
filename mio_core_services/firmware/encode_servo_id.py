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
        if args.current_id != BROADCAST_ID and not bus.ping(args.current_id):
            raise SystemExit(
                f"No reply from current ID {args.current_id} on {args.port} "
                "before writing. Check the ID, external power, and jumper B."
            )
        bus.set_id(args.new_id, current_id=args.current_id)
        time.sleep(0.05)
        if bus.ping(args.new_id):
            print(f"Servo now responds as ID {args.new_id}")
            return
        if (
            args.current_id != BROADCAST_ID
            and args.current_id != args.new_id
            and bus.ping(args.current_id)
        ):
            raise SystemExit(
                f"ID write did not take: servo still responds as {args.current_id}."
            )
        raise SystemExit(
            f"Wrote ID {args.new_id} but it did not reply. "
            "Check external power, jumper B, and that only one servo is connected."
        )


if __name__ == "__main__":
    main()
