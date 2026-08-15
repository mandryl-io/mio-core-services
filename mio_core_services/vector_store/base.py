from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mio_core_services.vector_store.embeddings import MioTextEmbedder


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

    @abstractmethod
    def add(self, documents: Sequence[Document]) -> None:
        """Embed and upsert documents, replacing any with matching ids."""

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Return the closest documents, most similar first."""

    @abstractmethod
    def delete(self, ids: Sequence[str]) -> None: ...

    @abstractmethod
    def count(self) -> int: ...
