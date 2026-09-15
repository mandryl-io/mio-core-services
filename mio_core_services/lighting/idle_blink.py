"""Idle blink: both eyes stay open, then close together for a human-length blink.

Timing is the adult average with a little gaussian noise so it does not look
mechanical:

  closed  ~200 ms  (100-400 ms in the literature; median ~170-192 ms)
  open    ~6.0 s   (~10 blinks/min; inter-blink 6.0-6.4 s in adults)

Same two white LEDs as `lighting.eyes` (GPIO23 / GPIO24). Started on boot by
`mio-eyes.service`.
"""

from __future__ import annotations

import argparse
import random
import time

from mio_core_services.lighting.eyes import (
    DEFAULT_LEFT_PIN,
    DEFAULT_RIGHT_PIN,
    Stopping,
    open_eyes,
)

# Schiffman / BioNumbers: 0.1-0.4 s. eNeuro 2024 median 170-192 ms.
BLINK_MEAN = 0.20
BLINK_SPREAD = 0.05
BLINK_MIN = 0.10
BLINK_MAX = 0.40

# Doughty 2002: 6.4 ± 2.4 s. Johnston 2013: mean 5.97 s.
OPEN_MEAN = 6.0
OPEN_SPREAD = 2.0
OPEN_MIN = 2.0
OPEN_MAX = 12.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def next_open() -> float:
    return _clamp(random.gauss(OPEN_MEAN, OPEN_SPREAD), OPEN_MIN, OPEN_MAX)


def next_blink() -> float:
    return _clamp(random.gauss(BLINK_MEAN, BLINK_SPREAD), BLINK_MIN, BLINK_MAX)


def _sleep(seconds: float, stopping: Stopping) -> None:
    deadline = time.monotonic() + seconds
    while not stopping.requested:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.02, left))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-pin", type=int, default=DEFAULT_LEFT_PIN)
    parser.add_argument("--right-pin", type=int, default=DEFAULT_RIGHT_PIN)
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="Run time. 0 runs until stopped.")
    parser.add_argument("--seed", type=int, help="Repeat a particular sequence.")
    parser.add_argument("--active-low", action="store_true",
                        help="If the LEDs are wired to sink, not source.")
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    eyes = open_eyes(args.left_pin, args.right_pin, args.active_low)
    stopping = Stopping()
    deadline = time.monotonic() + args.seconds if args.seconds else None
    blinks = 0

    print(
        f"left GPIO{args.left_pin}, right GPIO{args.right_pin}: "
        f"open ~{OPEN_MEAN:g}s, blink ~{int(BLINK_MEAN * 1000)}ms.\n"
        "Ctrl+C to stop.",
        flush=True,
    )

    try:
        eyes.set(True, True)
        while not stopping.requested:
            if deadline and time.monotonic() >= deadline:
                break
            opened = next_open()
            _sleep(opened, stopping)
            if stopping.requested:
                break
            if deadline and time.monotonic() >= deadline:
                break
            closed = next_blink()
            eyes.set(False, False)
            _sleep(closed, stopping)
            eyes.set(True, True)
            blinks += 1
            print(f"  blink {blinks}: closed {closed:.3f}s after {opened:.1f}s open",
                  flush=True)
    finally:
        eyes.off()
        eyes.close()
        print(f"\nStopped after {blinks} blink(s). Eyes off.")


if __name__ == "__main__":
    main()
