from collections.abc import Sequence
from typing import Any

import chromadb
from pydantic import PrivateAttr

from mio_core_services.common import MIO_LOCAL_VEC_MEMORY_STORE
from mio_core_services.vector_store.base import Document, MioVectorStore, SearchResult


class ChromaVectorStore(MioVectorStore):
    path: str

    _client: Any = PrivateAttr()
    _collection: Any = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        self._client = chromadb.PersistentClient(path=self.path)
        self._collection = self._client.get_or_create_collection(
            name=MIO_LOCAL_VEC_MEMORY_STORE,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, documents: Sequence[Document]) -> None:
        if not documents:
            return
        ids = [document.id for document in documents]
        existing = self._collection.get(ids=ids)["ids"]
        if existing:
            self._collection.delete(ids=existing)
        self._collection.add(
            ids=ids,
            documents=[document.text for document in documents],
            metadatas=[document.metadata or None for document in documents],
            embeddings=self.embedder.embed([document.text for document in documents]),
        )

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        count = self._collection.count()
        if count == 0 or limit <= 0:
            return []
        result = self._collection.query(
            query_embeddings=self.embedder.embed([query]),
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
        self._collection.delete(ids=list(ids))

    def count(self) -> int:
        return self._collection.count()
