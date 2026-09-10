from __future__ import annotations

import logging

import numpy as np

from mio_core_services.perception.backend import (
    DetectedFace,
    FaceBackend,
    NoOpFaceBackend,
)

logger = logging.getLogger(__name__)

_YAW_OFFSET = 0.25


class LocalFaceBackend:
    """InsightFace detect + embed + a facing filter from 5-point landmarks."""

    def __init__(self, yaw_offset: float = _YAW_OFFSET) -> None:
        from insightface.app import FaceAnalysis

        self._yaw_offset = yaw_offset
        self._app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("perception: LocalFaceBackend ready (buffalo_l)")

    def detect(
        self,
        image: bytes,
        *,
        size: tuple[int, int],
        format: str | None = None,
    ) -> list[DetectedFace]:
        width, height = size
        pixels = np.frombuffer(image, dtype=np.uint8)
        channels = 4 if (format or "").upper() in {"RGBA", "BGRA"} else 3
        frame = pixels.reshape((height, width, channels))
        if channels == 4:
            frame = frame[:, :, :3]
        if (format or "RGB").upper().startswith("RGB"):
            frame = frame[:, :, ::-1]
        faces: list[DetectedFace] = []
        for face in self._app.get(frame):
            embedding = np.asarray(face.embedding, dtype=np.float32)
            faces.append(
                DetectedFace(
                    embedding=embedding,
                    facing=_is_facing(np.asarray(face.kps), self._yaw_offset),
                    bbox=_bbox(face.bbox),
                )
            )
        return faces


def _is_facing(kps: np.ndarray, yaw_offset: float) -> bool:
    if kps.shape[0] < 3:
        return False
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_span = abs(float(right_eye[0] - left_eye[0]))
    if eye_span < 1.0:
        return False
    offset = abs(float(nose[0] - (left_eye[0] + right_eye[0]) / 2.0)) / eye_span
    return offset < yaw_offset


def _bbox(raw) -> tuple[float, float, float, float] | None:
    if raw is None or len(raw) < 4:
        return None
    return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))


def create_face_backend() -> FaceBackend:
    try:
        return LocalFaceBackend()
    except Exception:
        logger.warning(
            "perception: LocalFaceBackend unavailable, occupancy will stay empty",
            exc_info=True,
        )
        return NoOpFaceBackend()
