from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

from mio_core_services.constants import DEFAULT_FACE_MATCH_THRESHOLD
from mio_core_services.perception.backend import DetectedFace
from mio_core_services.perception.store import FaceStore, cosine

PRESENCE_PREFIX = "People facing the camera:"


@dataclass
class Occupant:
    person_id: str
    embedding: np.ndarray
    name: str | None = None
    new_this_session: bool = False


@dataclass
class OccupancySnapshot:
    occupants: list[Occupant] = field(default_factory=list)

    def presence_text(self) -> str | None:
        if not self.occupants:
            return None
        lines = [
            (
                f"{PRESENCE_PREFIX} you do not have to acknowledge them. "
                "If the user just said something that needs a reply, answer that "
                "first. Only address people listed here. Do not invent names."
            )
        ]
        for occupant in self.occupants:
            if occupant.name:
                label = occupant.name
            else:
                label = f"an unrecognized person (id={occupant.person_id})"
            if occupant.new_this_session:
                label += ", new this session"
                if occupant.name is None:
                    label += "; you may ask their name if it fits"
            lines.append(f"- {label}")
        return "\n".join(lines)

    def as_dicts(self) -> list[dict[str, str | bool | None]]:
        return [
            {
                "id": occupant.person_id,
                "name": occupant.name,
                "new_this_session": occupant.new_this_session,
            }
            for occupant in self.occupants
        ]


class Occupancy:
    """Who is facing the camera right now. Leave before a turn → gone, not queued."""

    def __init__(
        self,
        store: FaceStore,
        *,
        match_threshold: float = DEFAULT_FACE_MATCH_THRESHOLD,
    ) -> None:
        self._store = store
        self._match_threshold = match_threshold
        self._present: dict[str, Occupant] = {}
        self._seen: set[str] = set()

    @property
    def snapshot(self) -> OccupancySnapshot:
        return OccupancySnapshot(occupants=list(self._present.values()))

    def set_name(self, person_id: str, name: str) -> Occupant | None:
        record = self._store.set_name(person_id, name)
        occupant = self._present.get(person_id)
        if occupant is not None:
            occupant.name = name
        if record is None and occupant is None:
            return None
        return occupant

    def apply(self, detections: list[DetectedFace]) -> OccupancySnapshot:
        facing = [face for face in detections if face.facing]
        assigned: set[str] = set()
        next_present: dict[str, Occupant] = {}

        for face in facing:
            occupant = self._match(face.embedding, assigned)
            assigned.add(occupant.person_id)
            next_present[occupant.person_id] = occupant

        self._present = next_present
        return self.snapshot

    def _match(self, embedding: np.ndarray, assigned: set[str]) -> Occupant:
        present_hit = self._best_present(embedding, assigned)
        if present_hit is not None:
            return self._occupant_from_existing(present_hit.person_id, embedding, present_hit.name)

        record = self._store.match(
            embedding, threshold=self._match_threshold, exclude=assigned
        )
        if record is not None:
            return self._occupant_from_existing(record.id, embedding, record.name)

        person_id = uuid.uuid4().hex
        self._store.upsert(person_id, embedding)
        return self._occupant_from_existing(person_id, embedding, None)

    def _best_present(self, embedding: np.ndarray, assigned: set[str]) -> Occupant | None:
        best: Occupant | None = None
        best_score = self._match_threshold
        for occupant in self._present.values():
            if occupant.person_id in assigned:
                continue
            score = cosine(embedding, occupant.embedding)
            if score >= best_score:
                best = occupant
                best_score = score
        return best

    def _occupant_from_existing(
        self, person_id: str, embedding: np.ndarray, name: str | None
    ) -> Occupant:
        new_this_session = person_id not in self._seen
        self._seen.add(person_id)
        return Occupant(
            person_id=person_id,
            embedding=embedding,
            name=name,
            new_this_session=new_this_session,
        )
