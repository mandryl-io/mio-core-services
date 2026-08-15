from collections.abc import Sequence

import numpy as np
import pytest

from mio_core_services.vector_store.base import Document
from mio_core_services.vector_store.chroma import ChromaVectorStore
from mio_core_services.vector_store.embeddings import MioTextEmbedder

PARIS = Document(
    id="paris",
    text="Paris is the capital of France.",
    metadata={"country": "france"},
)
BERLIN = Document(
    id="berlin",
    text="Berlin is the capital of Germany.",
    metadata={"country": "germany"},
)
PYTHON = Document(
    id="python",
    text="Python is a programming language.",
    metadata={"topic": "code"},
)


class FakeEmbedder(MioTextEmbedder):
    """Bag-of-words vectors so tests do not need a real embedding model."""

    dimensions: int = 8
    vocabulary: tuple[str, ...] = (
        "paris",
        "france",
        "capital",
        "berlin",
        "germany",
        "python",
        "language",
        "tokyo",
    )

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append([float(lowered.count(word)) for word in self.vocabulary])
        return np.asarray(vectors, dtype=np.float32)


@pytest.fixture
def store(tmp_path) -> ChromaVectorStore:
    return ChromaVectorStore(path=str(tmp_path), embedder=FakeEmbedder())


def test_add_then_count(store: ChromaVectorStore):
    store.add([PARIS, BERLIN])
    assert store.count() == 2


def test_search_returns_closest_document(store: ChromaVectorStore):
    store.add([PARIS, PYTHON])
    results = store.search("What is the capital of France?")
    assert results[0].document.id == "paris"
    assert results[0].document.text == PARIS.text
    assert results[0].document.metadata == {"country": "france"}
    assert results[0].score > results[1].score


def test_search_respects_limit(store: ChromaVectorStore):
    store.add([PARIS, BERLIN, PYTHON])
    results = store.search("capital", limit=1)
    assert len(results) == 1


def test_search_on_empty_store_returns_nothing(store: ChromaVectorStore):
    assert store.search("capital") == []


def test_add_upserts_by_id(store: ChromaVectorStore):
    store.add([PARIS])
    store.add(
        [Document(id="paris", text="Paris is a city in France.", metadata={"updated": True})]
    )
    assert store.count() == 1
    result = store.search("Paris France")[0]
    assert result.document.text == "Paris is a city in France."
    assert result.document.metadata == {"updated": True}


def test_delete_removes_document(store: ChromaVectorStore):
    store.add([PARIS, BERLIN])
    store.delete(["paris"])
    assert store.count() == 1
    assert [result.document.id for result in store.search("capital")] == ["berlin"]


def test_persists_across_store_instances(tmp_path):
    embedder = FakeEmbedder()
    ChromaVectorStore(path=str(tmp_path), embedder=embedder).add([PARIS])
    reopened = ChromaVectorStore(path=str(tmp_path), embedder=embedder)
    results = reopened.search("capital of France")
    assert results[0].document.id == "paris"
    assert reopened.count() == 1
