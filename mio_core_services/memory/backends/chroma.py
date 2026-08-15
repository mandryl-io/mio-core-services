from collections.abc import Sequence
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from pydantic import Field, model_validator

from mio_core_services.constants import MIO_LOCAL_VEC_MEMORY_STORE
from mio_core_services.memory.store import Document, MioVectorStore, SearchResult

_DEFAULT_COLLECTION_METADATA = {"hnsw:space": "cosine"}


class ChromaVectorStore(MioVectorStore):
    path: str
    collection_metadata: dict[str, Any] = Field(
        default_factory=lambda: dict(_DEFAULT_COLLECTION_METADATA)
    )
    client: ClientAPI
    collection: Collection

    @model_validator(mode="before")
    @classmethod
    def _init_chroma(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        client = data.get("client") or chromadb.PersistentClient(path=data["path"])
        collection = data.get("collection") or client.get_or_create_collection(
            name=MIO_LOCAL_VEC_MEMORY_STORE,
            embedding_function=None,
            metadata=data.get("collection_metadata") or _DEFAULT_COLLECTION_METADATA,
        )
        return {**data, "client": client, "collection": collection}

    def add(self, documents: Sequence[Document]) -> None:
        if not documents:
            return
        ids = [document.id for document in documents]
        existing = self.collection.get(ids=ids)["ids"]
        if existing:
            self.collection.delete(ids=existing)
        self.collection.add(
            ids=ids,
            documents=[document.text for document in documents],
            metadatas=[document.metadata or None for document in documents],
            embeddings=self.embed([document.text for document in documents]),
        )

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        count = self.collection.count()
        if count == 0 or limit <= 0:
            return []
        result = self.collection.query(
            query_embeddings=self.embed([query]),
            n_results=min(limit, count),
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]
        return [
            SearchResult(
                document=Document(
                    id=doc_id,
                    text=text or "",
                    metadata=metadata or {},
                ),
                score=1.0 - distance,
            )
            for doc_id, text, metadata, distance in zip(
                ids, documents, metadatas, distances
            )
        ]

    def delete(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        self.collection.delete(ids=list(ids))

    def count(self) -> int:
        return self.collection.count()
