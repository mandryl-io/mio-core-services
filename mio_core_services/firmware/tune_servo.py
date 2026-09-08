"""Read and tune a servo's position loop, to stop it hunting when stationary."""

from __future__ import annotations

import argparse

from mio_core_services.firmware.sts3215 import (
    ADDR_CCW_DEAD_ZONE,
    ADDR_OVERLOAD_TORQUE,
    ADDR_PROTECTION_TIME,
    ADDR_PROTECTION_TORQUE,
    ADDR_RESPONSE_LEVEL,
    ADDR_CW_DEAD_ZONE,
    ADDR_D_COEFFICIENT,
    ADDR_I_COEFFICIENT,
    ADDR_MIN_STARTUP_FORCE,
    ADDR_P_COEFFICIENT,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)

# name -> (address, byte width, factory default)
REGISTERS = {
    "p": (ADDR_P_COEFFICIENT, 1, 32),
    "i": (ADDR_I_COEFFICIENT, 1, 0),
    "d": (ADDR_D_COEFFICIENT, 1, 32),
    "punch": (ADDR_MIN_STARTUP_FORCE, 2, 0),
    "cw-dead-zone": (ADDR_CW_DEAD_ZONE, 1, 1),
    "ccw-dead-zone": (ADDR_CCW_DEAD_ZONE, 1, 1),
}

# Registers worth seeing but not worth writing from here.
READ_ONLY = {
    "response-level": (ADDR_RESPONSE_LEVEL, 1, 1),
    "protection-torque": (ADDR_PROTECTION_TORQUE, 1, 20),
    "protection-time": (ADDR_PROTECTION_TIME, 1, 200),
    "overload-torque": (ADDR_OVERLOAD_TORQUE, 1, 80),
}

# The servo closes its loop across a gear train with 10-15 counts of lost
# motion. A dead zone of 4 sits inside that band, so the loop keeps correcting
# where it has no mechanical authority; and punch is the minimum torque needed
# to break static friction, so lowering it lets error build until the load
# breaks free and shoots through the backlash. Both were changed the wrong way.
# This is the recommended starting point to tune damping from.
BASELINE_PRESET = {
    "p": 32,
    "i": 0,
    "d": 32,
    "punch": 16,
    "cw-dead-zone": 1,
    "ccw-dead-zone": 1,
}


def _show(bus: STS3215Bus, servo_id: int) -> None:
    print(f"servo {servo_id}:")
    for name, (address, width, factory) in {**REGISTERS, **READ_ONLY}.items():
        value = bus.read_word(servo_id, address) if width == 2 else bus.read_byte(
            servo_id, address
        )
        flag = "" if value == factory else f"  (factory {factory})"
        print(f"  {name:<14} addr {address:>3}  = {value}{flag}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    for name in REGISTERS:
        parser.add_argument(f"--{name}", type=int, help=f"Set {name}.")
    parser.add_argument(
        "--dead-zone",
        type=int,
        help="Set both dead zones at once. Wider means less hunting, coarser holding.",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help=f"Restore the recommended starting point: {BASELINE_PRESET}. "
        "Tune --d upward from here.",
    )
    parser.add_argument(
        "--factory",
        action="store_true",
        help="Restore the factory values for every register listed.",
    )
    args = parser.parse_args()

    wanted: dict[str, int] = {}
    if args.baseline:
        wanted.update(BASELINE_PRESET)
    if args.factory:
        wanted.update({name: spec[2] for name, spec in REGISTERS.items()})
    if args.dead_zone is not None:
        wanted["cw-dead-zone"] = args.dead_zone
        wanted["ccw-dead-zone"] = args.dead_zone
    for name in REGISTERS:
        value = getattr(args, name.replace("-", "_"))
        if value is not None:
            wanted[name] = value

    with STS3215Bus(args.port, args.baudrate) as bus:
        if not wanted:
            _show(bus, args.id)
            print("\nNothing changed. Pass --baseline, --d N, or another register flag.")
            return

        print("before:")
        _show(bus, args.id)

        writes: dict[int, tuple[int, int]] = {}
        for name, value in wanted.items():
            address, width, _ = REGISTERS[name]
            ceiling = 1000 if width == 2 else 255
            if not 0 <= value <= ceiling:
                raise SystemExit(f"--{name} must be 0-{ceiling}, got {value}")
            writes[address] = (value, width)

        print(f"\nwriting { 'this is EEPROM and persists across power cycles' }...")
        bus.write_config(args.id, writes)

        print("\nafter:")
        _show(bus, args.id)
        print("\nTorque is off. Re-enable it by running any move command.")


if __name__ == "__main__":
    main()
