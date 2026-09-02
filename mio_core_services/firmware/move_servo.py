"""Move one STS3215 servo so we can confirm the Waveshare bus is alive."""

import argparse
import time

from mio_core_services.firmware.sts3215 import (
    CENTER_POSITION,
    DEFAULT_PORT,
    STS3215Bus,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument(
        "--position",
        type=int,
        default=CENTER_POSITION,
        help="Goal position 0–4095 (2048 is center).",
    )
    args = parser.parse_args()

    print(f"Moving servo {args.id} on {args.port} to {args.position}")
    with STS3215Bus(args.port) as bus:
        bus.move(args.position, servo_id=args.id)
        time.sleep(1.5)
    print("Done.")


if __name__ == "__main__":
    main()
