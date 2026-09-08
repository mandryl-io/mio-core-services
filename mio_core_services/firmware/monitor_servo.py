"""Sample a servo's voltage, load and temperature, to catch supply sag.

Servos draw far more current accelerating under load than holding still. A
supply that cannot hold voltage through that spike sags far enough for the
servo to latch an undervoltage condition and cut torque, which looks like
jitter or stuttering while travelling rather than an obvious power failure.
Run this while jogging the joint that misbehaves.
"""

from __future__ import annotations

import argparse
import sys
import time

from mio_core_services.firmware.sts3215 import (
    ADDR_PRESENT_LOAD,
    ADDR_PRESENT_TEMPERATURE,
    ADDR_PRESENT_VOLTAGE,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)

# Feetech reports load as a sign-magnitude word: bit 10 is direction.
LOAD_SIGN_BIT = 1 << 10
LOAD_MAGNITUDE = LOAD_SIGN_BIT - 1


def _signed_load(raw: int) -> int:
    magnitude = raw & LOAD_MAGNITUDE
    return -magnitude if raw & LOAD_SIGN_BIT else magnitude


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.1)
    args = parser.parse_args()

    print(f"Sampling servo {args.id} for {args.seconds:g}s. Move the joint now.\n")
    print(f"{'time':>6} {'volts':>6} {'load':>6} {'temp':>5}  {'position':>8}")

    voltages: list[float] = []
    start = time.monotonic()
    with STS3215Bus(args.port, args.baudrate) as bus:
        while time.monotonic() - start < args.seconds:
            try:
                volts = bus.read_byte(args.id, ADDR_PRESENT_VOLTAGE) / 10.0
                load = _signed_load(bus.read_word(args.id, ADDR_PRESENT_LOAD))
                temp = bus.read_byte(args.id, ADDR_PRESENT_TEMPERATURE)
                position = bus.position(servo_id=args.id)
            except TimeoutError:
                print("  (no reply)")
                continue
            voltages.append(volts)
            elapsed = time.monotonic() - start
            print(f"{elapsed:6.1f} {volts:6.1f} {load:6d} {temp:5d}  {position:8d}")
            time.sleep(args.interval)

    if not voltages:
        raise SystemExit("No samples returned.")

    low, high = min(voltages), max(voltages)
    print(f"\nvoltage: min {low:.1f}V  max {high:.1f}V  sag {high - low:.1f}V")
    if high - low >= 1.0:
        print(
            "\nThat is a large sag. The supply is struggling to deliver current\n"
            "under acceleration, which produces stuttering that looks like\n"
            "control jitter. Check the supply's current rating and the wiring\n"
            "back to it before tuning anything else.",
            file=sys.stderr,
        )
    elif low < 9.0:
        print(
            f"\nMinimum {low:.1f}V is low for this HAT (9-25V input).",
            file=sys.stderr,
        )
    else:
        print("\nSupply looks steady. Jitter is unlikely to be power related.")


if __name__ == "__main__":
    main()
