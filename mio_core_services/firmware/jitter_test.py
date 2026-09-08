"""Quantify jitter: hold a position and measure how much it actually moves.

"Still jittery" is hard to act on. This samples the position while the servo
holds, with torque on and then off, and reports peak-to-peak and RMS movement.
Torque on but torque off steady means the position loop is hunting. Both noisy
means it is mechanical or electrical, and no tuning will help.
"""

from __future__ import annotations

import argparse
import statistics
import time

from mio_core_services.firmware.servo_zeros_io import degrees_from_ticks
from mio_core_services.firmware.sts3215 import (
    ADDR_PRESENT_VOLTAGE,
    ADDR_STATUS,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import load_zeros


def _sample(bus: STS3215Bus, servo_id: int, seconds: float) -> tuple[list[int], list[float], int]:
    positions: list[int] = []
    volts: list[float] = []
    faults = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            positions.append(bus.position(servo_id=servo_id))
            volts.append(bus.read_byte(servo_id, ADDR_PRESENT_VOLTAGE) / 10.0)
            if bus.read_byte(servo_id, ADDR_STATUS):
                faults += 1
        except TimeoutError:
            continue
    return positions, volts, faults


def _describe(label: str, positions: list[int], target: int | None = None) -> float:
    if len(positions) < 2:
        print(f"  {label}: too few samples")
        return 0.0
    spread = max(positions) - min(positions)
    if target is not None:
        mean = statistics.fmean(positions)
        print(f"  {label:<12} settled at {mean:.1f}, {mean - target:+.1f} from goal")
    rms = statistics.pstdev(positions)
    print(
        f"  {label:<12} peak-to-peak {spread:4d} ticks "
        f"({degrees_from_ticks(spread):5.2f} deg)   rms {rms:5.2f}   "
        f"n={len(positions)}"
    )
    return spread


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-z", "--zeros", default="servo_zeros.json")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument(
        "--settle-timeout",
        type=float,
        default=20.0,
        help="How long to allow for reaching the hold position.",
    )
    parser.add_argument(
        "--at",
        type=int,
        help="Position to hold. Defaults to the servo's recorded zero.",
    )
    args = parser.parse_args()

    target = args.at
    if target is None:
        zeros = load_zeros(args.zeros)
        if args.id not in zeros:
            raise SystemExit(f"{args.zeros} has no entry for servo {args.id}")
        target = zeros[args.id].zero

    with STS3215Bus(args.port, args.baudrate) as bus:
        print(f"Servo {args.id}: holding {target} for {args.seconds:g}s each way.\n")

        bus.prepare(servo_id=args.id, speed=400, acc=30)
        bus.set_goal(target, servo_id=args.id)

        # Wait for arrival rather than a fixed delay: a fixed one samples the
        # servo mid-journey and reports the travel as jitter.
        deadline = time.monotonic() + args.settle_timeout
        arrived = False
        while time.monotonic() < deadline:
            try:
                if abs(bus.position(servo_id=args.id) - target) <= 8:
                    arrived = True
                    break
            except TimeoutError:
                pass
            time.sleep(0.05)
        if not arrived:
            raise SystemExit(
                f"Servo {args.id} did not reach {target} within "
                f"{args.settle_timeout:g}s. Check it is inside the travel limits."
            )
        time.sleep(1.0)  # let the approach settle before measuring

        print("torque ON (position loop active):")
        held, volts_on, faults_on = _sample(bus, args.id, args.seconds)
        spread_on = _describe("holding", held, target)

        bus.enable_torque(args.id, False)
        time.sleep(0.5)
        print("\ntorque OFF (mechanical only):")
        limp, volts_off, faults_off = _sample(bus, args.id, args.seconds)
        spread_off = _describe("limp", limp)

        if volts_on:
            print(
                f"\nvoltage while holding: {min(volts_on):.1f}-{max(volts_on):.1f}V"
                f"   faults: {faults_on + faults_off}"
            )

    print("\nverdict:")
    if spread_on <= 3:
        print("  Not jittering. Under 3 ticks is the encoder's own resolution.")
    elif spread_off >= spread_on * 0.6:
        print(
            "  It moves nearly as much limp as driven, so this is mechanical or\n"
            "  electrical, not the position loop. Look at backlash in the joint,\n"
            "  a loose horn, or supply sag. Tuning will not help."
        )
    else:
        print(
            "  It is much steadier limp than driven, so the position loop is\n"
            f"  hunting. Restore the baseline, then raise damping:\n"
            f"    tune_servo --id {args.id} --baseline\n"
            f"    tune_servo --id {args.id} --d 48"
        )


if __name__ == "__main__":
    main()
