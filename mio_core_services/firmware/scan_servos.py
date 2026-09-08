"""Scan the servo bus and report which IDs answer, with their positions."""

import argparse
import time

import serial

from mio_core_services.firmware.sts3215 import (
    ADDR_ID,
    ADDR_PRESENT_POSITION,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    POSITION_MAX,
    _status_params,
    read_packet,
)

REPLY_WAIT = 0.02


def _probe(ser: serial.Serial, servo_id: int, address: int, length: int) -> bytes | None:
    packet = read_packet(servo_id, address, length)
    ser.reset_input_buffer()
    ser.write(packet)
    ser.flush()
    time.sleep(REPLY_WAIT)
    return _status_params(ser.read(64), servo_id, length, packet)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument(
        "--max-id",
        type=int,
        default=253,
        help="Highest ID to probe. Lower it for a faster sweep.",
    )
    args = parser.parse_args()
    if not 1 <= args.max_id <= 253:
        raise SystemExit("--max-id must be 1-253")

    found: list[int] = []
    with serial.Serial(args.port, args.baudrate, timeout=0.03) as ser:
        print(f"Scanning {args.port} @ {args.baudrate} for IDs 1-{args.max_id}...")
        for servo_id in range(1, args.max_id + 1):
            if _probe(ser, servo_id, ADDR_ID, 1) is not None:
                found.append(servo_id)
                print(f"  ID {servo_id}: responding")

        if not found:
            raise SystemExit(
                "No servo answered. Check bus power, the three-wire connection, "
                "and see docs/waveshare-servo-hat.md."
            )

        print(f"\nFound {len(found)}: {found}")
        for servo_id in found:
            data = _probe(ser, servo_id, ADDR_PRESENT_POSITION, 2)
            if data is not None:
                position = (data[0] | (data[1] << 8)) & POSITION_MAX
                print(f"  ID {servo_id} position: {position}")


if __name__ == "__main__":
    main()
