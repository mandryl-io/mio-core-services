"""Cycle the head's RGB light: the three primaries, then the full spectrum.

One lap is red, green, blue -- the primaries on their own, which is also the
quickest way to see that the byte order is right -- followed by ROYGBIV across
the whole spectrum. Brightness steps to a new level on every transition, so
the light never repeats the same colour at the same intensity twice running.

Runs independently of the head motion: the servos are on the UART bus and this
is on GPIO18, so `mio-head.service` can stay up while this runs.
"""

from __future__ import annotations

import argparse
import signal
import time
from dataclasses import dataclass

from mio_core_services.lighting.pixels import (
    DEFAULT_GAMMA,
    DEFAULT_ORDER,
    DEFAULT_PIN,
    Color,
    StripConfig,
    open_strip,
)

# Tuned by eye on a WS2811, not taken from sRGB names. An additive LED's green
# channel dominates, so a literal orange (255,165,0) or yellow (255,255,0)
# comes out washed and near-identical; both are pulled well down here to keep
# the seven spectrum steps distinguishable from each other.
PRIMARIES: tuple[tuple[str, Color], ...] = (
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
)

SPECTRUM: tuple[tuple[str, Color], ...] = (
    ("red", (255, 0, 0)),
    ("orange", (255, 60, 0)),
    ("yellow", (255, 150, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("indigo", (60, 0, 190)),
    ("violet", (160, 0, 240)),
)

SEQUENCE = PRIMARIES + SPECTRUM

# Seven levels against ten colours: the two cycles are coprime, so the pairing
# of colour to brightness shifts every lap and takes 70 steps to repeat. The
# order is deliberately not a ramp -- consecutive levels differ widely enough
# that the change reads as a change, not as drift.
LEVELS: tuple[float, ...] = (1.0, 0.45, 0.75, 0.18, 0.9, 0.32, 0.6)

FRAME = 1.0 / 60.0


@dataclass(frozen=True)
class Beat:
    """One colour held at one brightness."""

    name: str
    color: Color
    brightness: float


def plan(colors=SEQUENCE, levels: tuple[float, ...] = LEVELS, laps: int = 0):
    """Pair each colour with the next brightness in the ladder.

    The brightness index runs continuously across laps rather than resetting,
    which is what makes the two cycle lengths interact. laps=0 never ends.
    """
    step = 0
    lap = 0
    while not laps or lap < laps:
        for name, color in colors:
            yield Beat(name, color, levels[step % len(levels)])
            step += 1
        lap += 1


class Stopping:
    """Latches on SIGINT or SIGTERM so Ctrl+C and systemd both stop cleanly."""

    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, *_: object) -> None:
        self.requested = True


def _mix(start: Color, end: Color, amount: float) -> Color:
    return tuple(
        round(a + (b - a) * amount) for a, b in zip(start, end)
    )  # type: ignore[return-value]


def _fade(strip, previous: Beat, beat: Beat, seconds: float, stopping) -> None:
    """Cross the colour and the brightness together over `seconds`."""
    started = time.monotonic()
    while not stopping.requested:
        amount = (time.monotonic() - started) / seconds
        if amount >= 1.0:
            break
        strip.show(
            _mix(previous.color, beat.color, amount),
            previous.brightness + (beat.brightness - previous.brightness) * amount,
        )
        time.sleep(FRAME)


def _hold(seconds: float, stopping) -> None:
    deadline = time.monotonic() + seconds
    while not stopping.requested and time.monotonic() < deadline:
        time.sleep(min(FRAME, max(0.0, deadline - time.monotonic())))


def _check_order(strip, stopping) -> None:
    """Name a channel, then light it, so a wrong byte order is obvious."""
    print("Each colour is named before it is shown. If the light disagrees with")
    print("the name, the byte order is wrong -- try --order RGB or BGR.\n")
    for name, color in PRIMARIES:
        if stopping.requested:
            break
        print(f"  {name}")
        strip.show(color, 1.0)
        _hold(2.0, stopping)
    strip.off()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pin", default=DEFAULT_PIN,
                        help="Blinka pin name. D18 is physical pin 12.")
    parser.add_argument("-n", "--count", type=int, default=1,
                        help="Pixels on the strand.")
    parser.add_argument("--order", default=DEFAULT_ORDER,
                        choices=("GRB", "RGB", "BGR", "RGBW", "GRBW"),
                        help="Pixel byte order. Most WS2811 parts are GRB.")
    parser.add_argument("--hold", type=float, default=1.5,
                        help="Seconds to sit on each colour.")
    parser.add_argument("--fade", type=float, default=0.35,
                        help="Seconds to cross between colours. 0 snaps.")
    parser.add_argument("--laps", type=int, default=0,
                        help="Laps of the sequence. 0 runs until stopped.")
    parser.add_argument("--levels", type=str, default=None,
                        help="Comma-separated brightness ladder, e.g. 1,0.5,0.2")
    parser.add_argument("--max-brightness", type=float, default=1.0,
                        help="Ceiling applied to every level, for a dimmer room.")
    parser.add_argument("--gamma", type=float, default=DEFAULT_GAMMA,
                        help="Brightness correction. 0 disables it.")
    parser.add_argument("--check-order", action="store_true",
                        help="Name and show red, green, blue, then exit.")
    parser.add_argument("--keep-lit", action="store_true",
                        help="Leave the last colour on at exit instead of going dark.")
    args = parser.parse_args()

    if args.hold < 0 or args.fade < 0:
        raise SystemExit("--hold and --fade cannot be negative")
    if not 0.0 < args.max_brightness <= 1.0:
        raise SystemExit("--max-brightness must be above 0.0 and at most 1.0")

    levels = LEVELS
    if args.levels:
        try:
            levels = tuple(float(part) for part in args.levels.split(","))
        except ValueError as exc:
            raise SystemExit(f"--levels must be numbers: {exc}") from exc
        if not levels or any(not 0.0 <= level <= 1.0 for level in levels):
            raise SystemExit("--levels must each be between 0.0 and 1.0")

    strip = open_strip(
        StripConfig(
            pin=args.pin,
            count=args.count,
            order=args.order,
            gamma=args.gamma,
            ceiling=args.max_brightness,
        )
    )
    stopping = Stopping()

    if args.check_order:
        _check_order(strip, stopping)
        return

    print(
        f"{args.count} pixel(s) on {args.pin}, order {args.order}. "
        f"{len(SEQUENCE)} colours against {len(levels)} brightness levels.\n"
        "Ctrl+C to stop."
    )

    previous = Beat("off", (0, 0, 0), 0.0)
    shown = 0
    try:
        for beat in plan(levels=levels, laps=args.laps):
            if stopping.requested:
                break
            print(f"  {beat.name:<7} {beat.brightness * 100:5.1f}%", flush=True)
            if args.fade:
                _fade(strip, previous, beat, args.fade, stopping)
            strip.show(beat.color, beat.brightness)
            previous = beat
            shown += 1
            _hold(args.hold, stopping)
    finally:
        if not args.keep_lit:
            strip.off()
        print(f"\nStopped after {shown} colours.{'' if args.keep_lit else ' Light off.'}")


if __name__ == "__main__":
    main()
