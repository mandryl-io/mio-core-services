"""Read the present position of one STS3215 servo."""

import argparse

from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--id", type=int, default=1)
    args = parser.parse_args()

    with STS3215Bus(args.port, args.baudrate) as bus:
        try:
            position = bus.position(servo_id=args.id)
        except TimeoutError:
            raise SystemExit(
                f"No reply from servo {args.id} on {args.port}. "
                "Check external power and the servo ID. For a Waveshare HAT (A) "
                "on /dev/serial0, select ESP32 mode, flash the transparent-"
                "transmission firmware, and use --baudrate 115200."
            )
    print(f"Servo {args.id} on {args.port} is at {position}")


if __name__ == "__main__":
    main()
