"""Idle blink: both eyes stay open, then close together for a human-length blink.

Timing comes from config/blink.yaml: published human means, shifted 1 SD
toward slow, then gaussian noise from the published spreads.

Each blink fades out then in over PWM, rather than slamming the pin.

Same two white LEDs as `lighting.eyes` (GPIO23 / GPIO24). Started on boot by
`mio-eyes.service`.
"""

from __future__ import annotations

import argparse
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

from mio_core_services.lighting.eyes import (
    DEFAULT_LEFT_PIN,
    DEFAULT_RIGHT_PIN,
    Stopping,
    open_eyes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = REPO_ROOT / "config" / "blink.yaml"


@dataclass(frozen=True)
class BlinkSettings:
    blink_mean: float
    blink_spread: float
    blink_min: float
    blink_max: float
    open_mean: float
    open_spread: float
    open_min: float
    open_max: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_yaml_floats(text: str) -> dict[str, float]:
    data: dict[str, float] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise SystemExit(f"blink settings: expected 'key: number', got {raw!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        try:
            data[key] = float(value.strip())
        except ValueError as exc:
            raise SystemExit(f"blink settings: {key} is not a number") from exc
    return data


def load_settings(path: Path | str = DEFAULT_SETTINGS) -> BlinkSettings:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise SystemExit(f"Could not read blink settings {path}: {exc}") from exc
    raw = _parse_yaml_floats(text)
    try:
        return BlinkSettings(
            blink_mean=raw["blink_mean"],
            blink_spread=raw["blink_spread"],
            blink_min=raw["blink_min"],
            blink_max=raw["blink_max"],
            open_mean=raw["open_mean"],
            open_spread=raw["open_spread"],
            open_min=raw["open_min"],
            open_max=raw["open_max"],
        )
    except KeyError as exc:
        raise SystemExit(f"{path} missing {exc.args[0]}") from exc


def next_open(settings: BlinkSettings) -> float:
    return _clamp(
        random.gauss(settings.open_mean, settings.open_spread),
        settings.open_min,
        settings.open_max,
    )


def next_blink(settings: BlinkSettings) -> float:
    return _clamp(
        random.gauss(settings.blink_mean, settings.blink_spread),
        settings.blink_min,
        settings.blink_max,
    )


def fade_level(start: float, end: float, t: float) -> float:
    """Brightness along a blink. Cosine ease so it doesn't look like a switch."""
    t = _clamp(t, 0.0, 1.0)
    eased = 0.5 - 0.5 * math.cos(math.pi * t)
    return start + (end - start) * eased


def _fade(eyes, start: float, end: float, seconds: float, stopping: Stopping) -> None:
    if seconds <= 0:
        eyes.level(end)
        return
    deadline = time.monotonic() + seconds
    while not stopping.requested:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        t = 1.0 - left / seconds
        eyes.level(fade_level(start, end, t))
        time.sleep(min(0.01, left))
    eyes.level(end)


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
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS),
                        help="YAML file with blink timing.")
    parser.add_argument("--seed", type=int, help="Repeat a particular sequence.")
    parser.add_argument("--active-low", action="store_true",
                        help="If the LEDs are wired to sink, not source.")
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    settings = load_settings(args.settings)
    eyes = open_eyes(args.left_pin, args.right_pin, args.active_low)
    stopping = Stopping()
    deadline = time.monotonic() + args.seconds if args.seconds else None
    blinks = 0

    print(
        f"left GPIO{args.left_pin}, right GPIO{args.right_pin}, "
        f"{args.settings}: open ~{settings.open_mean:g}s, "
        f"blink ~{int(settings.blink_mean * 1000)}ms.\n"
        "Ctrl+C to stop.",
        flush=True,
    )

    try:
        eyes.level(1.0)
        while not stopping.requested:
            if deadline and time.monotonic() >= deadline:
                break
            opened = next_open(settings)
            _sleep(opened, stopping)
            if stopping.requested:
                break
            if deadline and time.monotonic() >= deadline:
                break
            closed = next_blink(settings)
            half = closed / 2.0
            _fade(eyes, 1.0, 0.0, half, stopping)
            _fade(eyes, 0.0, 1.0, half, stopping)
            blinks += 1
            print(f"  blink {blinks}: closed {closed:.3f}s after {opened:.1f}s open",
                  flush=True)
    finally:
        eyes.off()
        eyes.close()
        print(f"\nStopped after {blinks} blink(s). Eyes off.")


if __name__ == "__main__":
    main()
