"""Read one STS3215 position with optional serial-link diagnostics."""

import argparse
import os
import stat
from pathlib import Path

from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)


def _port_preflight(port: str, baudrate: int) -> list[str]:
    """Validate the local UART and return facts useful for troubleshooting."""
    path = Path(port)
    if not path.exists():
        raise SystemExit(f"Serial port {port} does not exist.")

    resolved = path.resolve()
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise SystemExit(f"Cannot inspect serial port {resolved}: {exc}") from exc
    if not stat.S_ISCHR(mode):
        raise SystemExit(
            f"{port} resolves to {resolved}, which is not a character device."
        )

    readable = os.access(path, os.R_OK)
    writable = os.access(path, os.W_OK)
    facts = [
        f"port: {port} -> {resolved}",
        f"access: read={'yes' if readable else 'no'}, write={'yes' if writable else 'no'}",
        f"host baudrate: {baudrate}",
    ]
    if not readable or not writable:
        raise SystemExit(
            "\n".join([*facts, "The current user needs read/write access."])
        )

    try:
        cmdline = Path("/proc/cmdline").read_text().split()
    except OSError:
        cmdline = []
    serial_consoles = [item for item in cmdline if item.startswith("console=serial")]
    facts.append(
        "serial console: "
        + (
            f"CONFLICT ({', '.join(serial_consoles)})"
            if serial_consoles
            else "not active"
        )
    )
    return facts


def _failure_message(
    servo_id: int,
    port: str,
    baudrate: int,
    facts: list[str],
    error: TimeoutError,
) -> str:
    protocol_detail = str(error)
    received_nothing = "rx=empty" in protocol_detail
    interpretation = (
        "The UART opened and transmitted, but received zero bytes. This points to "
        "an inactive ESP32 forwarder/incorrect HAT firmware, the mode switch, servo "
        "power, or the three-wire connection."
        if received_nothing
        else "Bytes arrived, but they were not a valid STS3215 response. This points "
        "to a baud-rate/protocol mismatch or corrupted serial data."
    )
    lines = [
        f"No valid reply from servo ID {servo_id}.",
        *(f"  {fact}" for fact in facts),
        f"  protocol: {protocol_detail}",
        interpretation,
    ]
    if port == "/dev/serial0" and baudrate != 115_200:
        lines.append(
            "For Waveshare HAT (A) ESP32 forwarding, retry with --baudrate 115200."
        )
    lines.extend(
        [
            "No ID or calibration data was changed.",
            (
                "Check: external servo voltage, one servo connected as ID 1, ESP32 "
                "mode, and Waveshare transparent-transmission firmware/forwarding "
                "enabled."
            ),
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print UART preflight details even when the servo responds.",
    )
    args = parser.parse_args()

    facts = _port_preflight(args.port, args.baudrate)
    try:
        with STS3215Bus(args.port, args.baudrate) as bus:
            position = bus.position(servo_id=args.id)
    except TimeoutError as exc:
        raise SystemExit(
            _failure_message(args.id, args.port, args.baudrate, facts, exc)
        ) from exc
    except OSError as exc:
        raise SystemExit(
            "\n".join(
                [
                    "Serial port preflight passed, but opening or using the UART failed:",
                    *(f"  {fact}" for fact in facts),
                    f"  operating-system error: {exc}",
                ]
            )
        ) from exc

    if args.diagnose:
        print("Serial diagnostics:")
        for fact in facts:
            print(f"  {fact}")
    print(f"Servo {args.id} on {args.port} is at {position}")


if __name__ == "__main__":
    main()
