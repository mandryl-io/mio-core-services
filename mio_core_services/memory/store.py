from abc import abstractmethod
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from mio_core_services.memory.embeddings import MioTextEmbedder


class Document(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    document: Document
    score: float


class MioVectorStore(BaseModel):
    """Interface every vector database backend must implement."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    embedder: MioTextEmbedder

    @classmethod
    def load(
        cls,
        store_name: str,
        *,
        backend: Literal["chroma"] = "chroma",
        embedder: MioTextEmbedder | None = None,
        **kwargs: Any,
    ) -> "MioVectorStore":
        """Open a store by name, creating it if it does not exist yet.

        ``backend`` defaults to Chroma and ``embedder`` defaults to
        ``SentenceTransformerEmbedder``. For Chroma, ``store_name`` is the
        persistent directory; an existing collection there is reused.
        """
        if embedder is None:
            from mio_core_services.memory.embeddings import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder()
        if backend == "chroma":
            from mio_core_services.memory.backends.chroma import ChromaVectorStore

            return ChromaVectorStore(path=store_name, embedder=embedder, **kwargs)
        raise ValueError(f"Unsupported vector store backend: {backend}")

    def embed(
        self,
        texts: Sequence[str],
        embedder: MioTextEmbedder | None = None,
    ) -> np.ndarray:
        """Embed texts with embedder, defaulting to this store's embedder."""
        chosen = embedder or self.embedder
        if not texts:
            return np.empty((0, chosen.dimensions), dtype=np.float32)
        embeddings = np.asarray(chosen.embed(list(texts)), dtype=np.float32)
        expected = (len(texts), chosen.dimensions)
        if embeddings.shape != expected:
            raise ValueError(
                f"embedder returned shape {embeddings.shape}, expected {expected}"
            )
        return embeddings

    @abstractmethod
    def add(self, documents: Sequence[Document]) -> None:
        """Embed and upsert documents, replacing any with matching ids."""

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Return the closest documents, most similar first."""

    @abstractmethod
    def delete(self, ids: Sequence[str]) -> None:
        """Remove documents by id. Missing ids are ignored."""

    @abstractmethod
    def count(self) -> int:
        """Return the number of stored documents. If it is not implemented for
        a vector store backend, returns -1."""
        return -1
