from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class DetectedFace:
    embedding: np.ndarray
    facing: bool
    bbox: tuple[float, float, float, float] | None = None


class FaceBackend(Protocol):
    """Detect faces in a raw camera frame. No identity, no session state."""

    def detect(
        self,
        image: bytes,
        *,
        size: tuple[int, int],
        format: str | None = None,
    ) -> list[DetectedFace]:
        """Return faces found in ``image`` (row-major pixels of ``size``)."""


class NoOpFaceBackend:
    """Used when a local detector is unavailable (evals, missing extras)."""

    def detect(
        self,
        image: bytes,
        *,
        size: tuple[int, int],
        format: str | None = None,
    ) -> list[DetectedFace]:
        return []
