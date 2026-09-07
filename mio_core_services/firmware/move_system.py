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
    parser.add_argument(
        "--position-1",
        type=int,
        default=CENTER_POSITION,
        help="Goal position for servo 1 0–4095 (2048 is center).",
    )
    parser.add_argument(
        "--position-2",
        type=int,
        default=CENTER_POSITION,
        help="Goal position for servo 2 0–4095 (2048 is center).",
    )
    args = parser.parse_args()

    print(f"Moving system on {args.port} to {args.position_1} and {args.position_2}")
    with STS3215Bus(args.port) as bus:
        bus.move(args.position_1, servo_id=1)
        bus.move(args.position_2, servo_id=2)
    print("Done.")


if __name__ == "__main__":
    main()
