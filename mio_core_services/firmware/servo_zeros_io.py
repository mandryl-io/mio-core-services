"""Shared read/merge/write helpers for the servo zeros JSON file."""

from __future__ import annotations

import json
import os

from mio_core_services.firmware.sts3215 import POSITION_MAX

TICKS_PER_REVOLUTION = POSITION_MAX + 1
TICKS_PER_DEGREE = TICKS_PER_REVOLUTION / 360.0


def ticks_from_degrees(degrees: float) -> int:
    return round(degrees * TICKS_PER_DEGREE)


def degrees_from_ticks(ticks: int) -> float:
    return ticks / TICKS_PER_DEGREE


def read_records(path: str) -> dict[str, dict[str, int]]:
    """Return the existing records, or an empty dict when the file is absent."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            raw = json.load(handle)
    except OSError as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"{path} must be a JSON object of id -> zero/limits")
    return raw


def merge_record(
    path: str,
    servo_id: int,
    zero: int,
    minimum: int,
    maximum: int,
) -> dict[str, dict[str, int]]:
    """Write one servo's calibration, leaving other servos in the file intact."""
    if not 0 <= minimum <= zero <= maximum <= POSITION_MAX:
        raise SystemExit(
            f"servo {servo_id}: need 0 <= min <= zero <= max <= {POSITION_MAX}, "
            f"got min={minimum} zero={zero} max={maximum}"
        )
    records = read_records(path)
    records[str(servo_id)] = {"zero": zero, "min": minimum, "max": maximum}
    with open(path, "w") as handle:
        json.dump(records, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return records
