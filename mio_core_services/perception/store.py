from __future__ import annotations

from dataclasses import dataclass

import chromadb
import numpy as np
from chromadb.api.models.Collection import Collection

from mio_core_services.constants import (
    DEFAULT_FACE_MATCH_THRESHOLD,
    MIO_FACE_COLLECTION,
)


def _normalize(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector
    return vector / norm


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(_normalize(a), _normalize(b)))


@dataclass
class FaceRecord:
    id: str
    embedding: np.ndarray
    name: str | None = None


class FaceStore:
    """Persistent face embeddings. Not the text knowledge base."""

    def __init__(
        self,
        path: str | None = None,
        *,
        collection_name: str = MIO_FACE_COLLECTION,
    ) -> None:
        self._records: dict[str, FaceRecord] = {}
        self._collection: Collection | None = None
        if path is not None:
            client = chromadb.PersistentClient(path=path)
            self._collection = client.get_or_create_collection(
                name=collection_name,
                embedding_function=None,
                metadata={"hnsw:space": "cosine"},
            )
            self._load()

    def _load(self) -> None:
        if self._collection is None:
            return
        dumped = self._collection.get(include=["embeddings", "metadatas"])
        ids = dumped.get("ids") or []
        embeddings = dumped.get("embeddings")
        metadatas = dumped.get("metadatas")
        if embeddings is None:
            embeddings = []
        if metadatas is None:
            metadatas = []
        for person_id, embedding, metadata in zip(ids, embeddings, metadatas):
            metadata = metadata or {}
            name = metadata.get("name") or None
            self._records[person_id] = FaceRecord(
                id=person_id,
                embedding=_normalize(embedding),
                name=name,
            )

    def upsert(
        self,
        person_id: str,
        embedding: np.ndarray,
        name: str | None = None,
    ) -> FaceRecord:
        existing = self._records.get(person_id)
        if name is None and existing is not None:
            name = existing.name
        record = FaceRecord(
            id=person_id,
            embedding=_normalize(embedding),
            name=name,
        )
        self._records[person_id] = record
        if self._collection is not None:
            existing_ids = self._collection.get(ids=[person_id])["ids"]
            if existing_ids:
                self._collection.delete(ids=existing_ids)
            self._collection.add(
                ids=[person_id],
                embeddings=[record.embedding.tolist()],
                documents=[name or person_id],
                metadatas=[{"name": name or ""}],
            )
        return record

    def set_name(self, person_id: str, name: str) -> FaceRecord | None:
        record = self._records.get(person_id)
        if record is None:
            return None
        return self.upsert(person_id, record.embedding, name=name)

    def get(self, person_id: str) -> FaceRecord | None:
        return self._records.get(person_id)

    def match(
        self,
        embedding: np.ndarray,
        *,
        threshold: float = DEFAULT_FACE_MATCH_THRESHOLD,
        exclude: set[str] | None = None,
    ) -> FaceRecord | None:
        excluded = exclude or set()
        best: FaceRecord | None = None
        best_score = threshold
        for record in self._records.values():
            if record.id in excluded:
                continue
            score = cosine(embedding, record.embedding)
            if score >= best_score:
                best = record
                best_score = score
        return best

    def count(self) -> int:
        return len(self._records)
