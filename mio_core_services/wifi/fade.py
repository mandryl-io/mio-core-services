"""Slow cosine on/off for the eyes while WiFi setup is waiting."""

from __future__ import annotations

import math
import time

FADE_PERIOD = 3.0
FADE_STEP = 0.02


def fade_level(elapsed: float, period: float = FADE_PERIOD) -> float:
    """Brightness 1 → 0 → 1 over `period` seconds. Starts fully on."""
    if period <= 0:
        return 0.0
    return 0.5 + 0.5 * math.cos(2.0 * math.pi * (elapsed % period) / period)


def run_fade(eyes, stopping, period: float = FADE_PERIOD, step: float = FADE_STEP) -> None:
    started = time.monotonic()
    try:
        while not stopping.requested:
            eyes.level(fade_level(time.monotonic() - started, period))
            deadline = time.monotonic() + step
            while not stopping.requested:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                time.sleep(min(0.02, left))
    finally:
        eyes.off()
