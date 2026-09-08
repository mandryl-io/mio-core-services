"""Set a servo's symmetric travel limits, then verify them with a sweep."""

from __future__ import annotations

import argparse
import sys
import time

from mio_core_services.firmware.servo_zeros_io import (
    degrees_from_ticks,
    merge_record,
    read_records,
    ticks_from_degrees,
)
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    POSITION_MAX,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import (
    CONFIRM_KEYS,
    HOLD_DT,
    JOG_DT,
    LEFT_KEYS,
    QUIT_KEYS,
    RIGHT_KEYS,
    RawTerminal,
)

ARRIVE_TOLERANCE = 20
CENTRE_PAUSE = 0.5
SWEEP_CYCLES = 3


def _say(message: str = "") -> None:
    """Print a line that renders correctly whether or not the tty is raw."""
    sys.stdout.write(f"{message}\r\n")
    sys.stdout.flush()


def _settle(bus: STS3215Bus, servo_id: int, goal: int, timeout: float = 15.0) -> int:
    bus.set_goal(goal, servo_id=servo_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.08)
        if abs(bus.position(servo_id=servo_id) - goal) <= ARRIVE_TOLERANCE:
            break
    return bus.position(servo_id=servo_id)


def _wait_for_key(terminal: RawTerminal, accepted: set[str]) -> str:
    while True:
        key = terminal.poll_key(0.1)
        if key is None:
            continue
        if key in QUIT_KEYS:
            raise SystemExit("\r\nAborted. Nothing was saved.")
        lowered = key.lower()
        if lowered in accepted:
            return lowered


def _jog_to(
    bus: STS3215Bus,
    terminal: RawTerminal,
    servo_id: int,
    start: int,
    step: int,
) -> int:
    """Arrow-key jog until Enter, returning the position settled on."""
    position = start
    direction = 0
    last_hold = 0.0
    while True:
        key = terminal.poll_key(JOG_DT)
        now = time.monotonic()
        while key is not None:
            if key in LEFT_KEYS:
                direction, last_hold = -1, now
            elif key in RIGHT_KEYS:
                direction, last_hold = 1, now
            elif key in CONFIRM_KEYS:
                return bus.position(servo_id=servo_id)
            elif key in QUIT_KEYS:
                raise SystemExit("\r\nAborted. Nothing was saved.")
            key = terminal.poll_key(0)
        if now - last_hold > HOLD_DT:
            direction = 0
            continue
        position = max(0, min(POSITION_MAX, position + direction * step))
        bus.set_goal(position, servo_id=servo_id)
        sys.stdout.write(
            f"\r\x1b[K  {position}  "
            f"({degrees_from_ticks(position - start):+.1f} deg from here)"
        )
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=1, help="Servo to calibrate.")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-o", "--output", default="servo_zeros.json")
    parser.add_argument(
        "--degrees",
        type=float,
        default=180.0,
        help="Total travel to try first, split evenly either side of zero.",
    )
    parser.add_argument(
        "--zero",
        type=int,
        help="Zero position. Defaults to the value already in the output file.",
    )
    parser.add_argument("--step", type=int, default=4, help="Ticks per jog tick.")
    parser.add_argument("--speed", type=int, default=800)
    args = parser.parse_args()
    if args.degrees <= 0:
        raise SystemExit("--degrees must be > 0")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY for arrow-key jogging. Run with: ssh -t ...")

    zero = args.zero
    if zero is None:
        record = read_records(args.output).get(str(args.id))
        if record is None:
            raise SystemExit(
                f"No zero recorded for servo {args.id} in {args.output}. "
                "Run set_zero first, or pass --zero."
            )
        zero = int(record["zero"])

    half = ticks_from_degrees(args.degrees / 2)
    print(f"Servo {args.id}: zero is {zero}.")
    print(
        f"Trying {args.degrees:g} deg total travel: "
        f"{args.degrees / 2:g} deg each side ({half} ticks)."
    )
    print()
    print("Unplug the servo wire running on to the next joint first, so it")
    print("cannot be pulled or twisted while this rotates.")
    print()

    with STS3215Bus(args.port, args.baudrate) as bus:
        bus.prepare(servo_id=args.id, speed=args.speed, acc=30)
        with RawTerminal() as terminal:
            _say("Press Enter when the wire is unplugged, or q to abort.")
            _wait_for_key(terminal, set(CONFIRM_KEYS) | {"\r", "\n"})

            candidate = max(0, min(POSITION_MAX, zero + half))
            if candidate != zero + half:
                _say(f"Clamped to {candidate}: {zero + half} is off the encoder.")
            _say(f"Moving to {candidate}...")
            reached = _settle(bus, args.id, candidate)
            _say(f"Reached {reached}.")
            _say()

            _say("Is that the right amount of travel? y = yes, n = let me set it.")
            answer = _wait_for_key(terminal, {"y", "n"})

            if answer == "n":
                _say()
                _say("Jog to the furthest point you want in this direction.")
                _say("Hold left/right, Enter to accept, q to abort.")
                reached = _jog_to(bus, terminal, args.id, reached, args.step)
                _say()

            travel = abs(reached - zero)
            if travel == 0:
                raise SystemExit("\r\nTravel is zero; nothing to calibrate.")
            minimum = zero - travel
            maximum = zero + travel
            _say(
                f"Travel {travel} ticks ({degrees_from_ticks(travel):.1f} deg) "
                "each side."
            )
            if minimum < 0 or maximum > POSITION_MAX:
                clamped_min = max(0, minimum)
                clamped_max = min(POSITION_MAX, maximum)
                _say(
                    f"That does not fit symmetrically: {minimum}-{maximum} "
                    f"exceeds 0-{POSITION_MAX}. Clamping to "
                    f"{clamped_min}-{clamped_max}."
                )
                minimum, maximum = clamped_min, clamped_max
            _say(f"Limits: {minimum} - {maximum}, zero {zero}.")
            _say()

            _say("Returning to centre...")
            _settle(bus, args.id, zero)

            _say(f"Sweeping {SWEEP_CYCLES} times, pausing at centre each pass.")
            for cycle in range(1, SWEEP_CYCLES + 1):
                for label, goal in (
                    ("max", maximum),
                    ("centre", zero),
                    ("min", minimum),
                    ("centre", zero),
                ):
                    at = _settle(bus, args.id, goal)
                    _say(f"  cycle {cycle}: {label} {goal} -> at {at}")
                    if label == "centre":
                        time.sleep(CENTRE_PAUSE)

            _say()
            _say("Holding at centre.")

        merge_record(args.output, args.id, zero, minimum, maximum)
        print(f"Wrote servo {args.id} to {args.output}: "
              f"zero={zero} min={minimum} max={maximum}")
        print("Plug the onward servo wire back in.")


if __name__ == "__main__":
    main()
