"""The two white eye LEDs: left three times, right three times, then both.

One lap is left flashing three times, right flashing three times, then both
blinking together for three seconds. It repeats until stopped.

Wiring, on the same header as the RGB light:

    pin 14  GND     both LED grounds
    pin 16  GPIO23  left eye
    pin 18  GPIO24  right eye

Which physical eye is "left" depends on which way round you soldered them and
whether you mean the robot's left or yours. Swap --left-pin and --right-pin if
it flashes the wrong one first.

The pattern is generated as timed steps, separate from the pins, so it can be
tested off the Pi.
"""

from __future__ import annotations

import argparse
import signal
import time
from dataclasses import dataclass

DEFAULT_LEFT_PIN = 23
DEFAULT_RIGHT_PIN = 24

# Slow enough to read as a deliberate flash rather than a glitch.
FLASHES = 3
FLASH_ON = 0.12
FLASH_OFF = 0.18
GAP = 0.45  # between the left group and the right group
BOTH_SECONDS = 3.0
BLINK_ON = 0.12
BLINK_OFF = 0.12

EPSILON = 1e-9


@dataclass(frozen=True)
class Step:
    """Both lamps' state, held for `seconds`."""

    left: bool
    right: bool
    seconds: float


def pattern(
    flashes: int = FLASHES,
    flash_on: float = FLASH_ON,
    flash_off: float = FLASH_OFF,
    gap: float = GAP,
    both_seconds: float = BOTH_SECONDS,
    blink_on: float = BLINK_ON,
    blink_off: float = BLINK_OFF,
) -> list[Step]:
    """One lap: left xN, right xN, then both blinking for `both_seconds`."""
    steps: list[Step] = []

    for index, side in enumerate((0, 1)):
        for flash in range(flashes):
            steps.append(Step(side == 0, side == 1, flash_on))
            # No trailing dark step: the gap or the blink phase covers it.
            if flash < flashes - 1:
                steps.append(Step(False, False, flash_off))
        if index == 0 and gap:
            steps.append(Step(False, False, gap))

    if gap:
        steps.append(Step(False, False, gap))

    # Blink whole cycles, trimming the last so the phase lasts exactly
    # both_seconds rather than overrunning by part of a cycle.
    remaining = both_seconds
    lit = True
    while remaining > EPSILON:
        span = min(blink_on if lit else blink_off, remaining)
        steps.append(Step(lit, lit, span))
        remaining -= span
        lit = not lit

    return steps


class Stopping:
    """Latches on SIGINT or SIGTERM so Ctrl+C and systemd both stop cleanly."""

    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, *_: object) -> None:
        self.requested = True


class Eyes:
    """The two lamps. Nothing here knows about the pattern."""

    def __init__(self, left, right) -> None:
        self._left = left
        self._right = right

    def set(self, left: bool, right: bool) -> None:
        self._left.value = 1 if left else 0
        self._right.value = 1 if right else 0

    def off(self) -> None:
        self.set(False, False)

    def close(self) -> None:
        self._left.close()
        self._right.close()


def open_eyes(left_pin: int, right_pin: int, active_low: bool) -> Eyes:
    """Claim both pins, or explain what is missing."""
    try:
        from gpiozero import LED
    except ImportError as exc:
        raise SystemExit(
            f"Cannot import gpiozero ({exc}).\n"
            "On the Pi: sudo apt install -y python3-gpiozero python3-lgpio\n"
            "The venv needs --system-site-packages to see them."
        ) from exc

    try:
        left = LED(left_pin, active_high=not active_low)
        right = LED(right_pin, active_high=not active_low)
    except Exception as exc:  # busy pin, no permission, no gpiochip
        raise SystemExit(
            f"Cannot claim GPIO {left_pin} and {right_pin} ({exc}).\n"
            "Another process may hold the pins, or your user may not be in the "
            "gpio group. Check with: id -nG"
        ) from exc

    return Eyes(left, right)


def _sleep(seconds: float, stopping: Stopping) -> None:
    deadline = time.monotonic() + seconds
    while not stopping.requested:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.02, left))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--left-pin", type=int, default=DEFAULT_LEFT_PIN,
                        help="BCM number for the left eye. GPIO23 is pin 16.")
    parser.add_argument("--right-pin", type=int, default=DEFAULT_RIGHT_PIN,
                        help="BCM number for the right eye. GPIO24 is pin 18.")
    parser.add_argument("--flashes", type=int, default=FLASHES,
                        help="Flashes per eye before the pair blink.")
    parser.add_argument("--flash-on", type=float, default=FLASH_ON)
    parser.add_argument("--flash-off", type=float, default=FLASH_OFF)
    parser.add_argument("--gap", type=float, default=GAP,
                        help="Dark pause between phases.")
    parser.add_argument("--both-seconds", type=float, default=BOTH_SECONDS,
                        help="How long the pair blink together.")
    parser.add_argument("--blink-on", type=float, default=BLINK_ON)
    parser.add_argument("--blink-off", type=float, default=BLINK_OFF)
    parser.add_argument("--laps", type=int, default=0,
                        help="Laps to run. 0 runs until stopped.")
    parser.add_argument("--active-low", action="store_true",
                        help="If the LEDs are wired to sink, not source.")
    args = parser.parse_args()

    if args.flashes < 1:
        raise SystemExit("--flashes must be at least 1")
    for name in ("flash_on", "flash_off", "gap", "both_seconds",
                 "blink_on", "blink_off"):
        if getattr(args, name) < 0:
            raise SystemExit(f"--{name.replace('_', '-')} cannot be negative")
    if args.blink_on <= 0 or args.blink_off <= 0:
        raise SystemExit("--blink-on and --blink-off must be above 0")

    steps = pattern(
        flashes=args.flashes,
        flash_on=args.flash_on,
        flash_off=args.flash_off,
        gap=args.gap,
        both_seconds=args.both_seconds,
        blink_on=args.blink_on,
        blink_off=args.blink_off,
    )
    lap_time = sum(step.seconds for step in steps)

    eyes = open_eyes(args.left_pin, args.right_pin, args.active_low)
    stopping = Stopping()

    print(
        f"left GPIO{args.left_pin}, right GPIO{args.right_pin}. "
        f"{args.flashes} each, then both for {args.both_seconds:g}s "
        f"-- {lap_time:.1f}s a lap.\nCtrl+C to stop."
    )

    laps = 0
    try:
        while not stopping.requested:
            laps += 1
            print(f"  lap {laps}", flush=True)
            for step in steps:
                if stopping.requested:
                    break
                eyes.set(step.left, step.right)
                _sleep(step.seconds, stopping)
            if args.laps and laps >= args.laps:
                break
    finally:
        eyes.off()
        eyes.close()
        print(f"\nStopped after {laps} lap(s). Eyes off.")


if __name__ == "__main__":
    main()
