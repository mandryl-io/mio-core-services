"""Rewrite wakephrase YAML paths so training can run on a remote volume."""

from __future__ import annotations

from pathlib import Path
from typing import Any

VOLUME_MOUNT = Path("/vol/wakephrase")
REMOTE_DATA_DIR = VOLUME_MOUNT / "data"
REMOTE_OUTPUT_DIR = VOLUME_MOUNT / "output"


def _norm_parts(path: Path) -> tuple[str, ...]:
    parts = path.parts
    if parts and parts[0] == ".":
        parts = parts[1:]
    return parts


def rebase_path(path: str, old_root: str, new_root: Path) -> str:
    """Map a path that lived under *old_root* onto *new_root*.

    Absolute paths are left unchanged so a config can pin a specific location.
    """
    raw = Path(path)
    if raw.is_absolute():
        return str(raw)
    old_parts = _norm_parts(Path(old_root))
    path_parts = _norm_parts(raw)
    if old_parts and path_parts[: len(old_parts)] == old_parts:
        rest = path_parts[len(old_parts) :]
        return str(new_root.joinpath(*rest)) if rest else str(new_root)
    return str(raw)


def remount_config(
    data: dict[str, Any],
    *,
    data_dir: Path = REMOTE_DATA_DIR,
    output_dir: Path = REMOTE_OUTPUT_DIR,
) -> dict[str, Any]:
    """Point data/output (and augmentation audio roots) at a remote volume."""
    remounted = dict(data)
    old_data_dir = str(remounted.get("data_dir") or "./data")
    remounted["data_dir"] = str(data_dir)
    remounted["output_dir"] = str(output_dir)

    augmentation = dict(remounted.get("augmentation") or {})
    for key in ("background_paths", "rir_paths"):
        if key not in augmentation:
            continue
        augmentation[key] = [
            rebase_path(path, old_data_dir, data_dir) for path in augmentation[key]
        ]
    if augmentation:
        remounted["augmentation"] = augmentation
    return remounted
