from collections.abc import Sequence

import numpy as np
import pytest

from mio_core_services.vector_store.chroma import ChromaVectorStore
from mio_core_services.vector_store.embeddings import (
    SentenceTransformerEmbedder,
    _MODEL_CACHE,
)
from tests.test_chroma import FakeEmbedder


class _FakeSentenceTransformer:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.encode_calls: list[list[str]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 384

    def encode(self, texts: Sequence[str], **kwargs) -> np.ndarray:
        self.encode_calls.append(list(texts))
        return np.ones((len(texts), 384), dtype=np.float32)


@pytest.fixture(autouse=True)
def _clear_model_cache():
    _MODEL_CACHE.clear()
    yield
    _MODEL_CACHE.clear()


def test_sentence_transformer_embedder_loads_model_once(monkeypatch):
    constructed: list[str] = []

    def fake_loader(model_name: str) -> _FakeSentenceTransformer:
        constructed.append(model_name)
        cached = _MODEL_CACHE.get(model_name)
        if cached is None:
            cached = _FakeSentenceTransformer(model_name)
            _MODEL_CACHE[model_name] = cached
        return cached

    monkeypatch.setattr(
        "mio_core_services.vector_store.embeddings._sentence_transformer",
        fake_loader,
    )
    first = SentenceTransformerEmbedder()
    second = SentenceTransformerEmbedder()
    first.embed(["hello"])
    second.embed(["world"])
    assert constructed == ["thenlper/gte-small"]
    assert first._model is second._model
    assert len(first._model.encode_calls) == 2


def test_sentence_transformer_embedder_returns_numpy_matrix(monkeypatch):
    monkeypatch.setattr(
        "mio_core_services.vector_store.embeddings._sentence_transformer",
        lambda model_name: _FakeSentenceTransformer(model_name),
    )
    embedder = SentenceTransformerEmbedder()
    embeddings = embedder.embed(["one", "two"])
    assert isinstance(embeddings, np.ndarray)
    assert embeddings.shape == (2, 384)
    assert embeddings.dtype == np.float32
    assert embedder.dimensions == 384


def test_sentence_transformer_embedder_empty_texts(monkeypatch):
    monkeypatch.setattr(
        "mio_core_services.vector_store.embeddings._sentence_transformer",
        lambda model_name: _FakeSentenceTransformer(model_name),
    )
    embeddings = SentenceTransformerEmbedder().embed([])
    assert embeddings.shape == (0, 384)


def test_sentence_transformer_embedder_rejects_dimension_mismatch(monkeypatch):
    class WrongWidth(_FakeSentenceTransformer):
        def get_sentence_embedding_dimension(self) -> int:
            return 128

    monkeypatch.setattr(
        "mio_core_services.vector_store.embeddings._sentence_transformer",
        lambda model_name: WrongWidth(model_name),
    )
    with pytest.raises(ValueError, match="128-d"):
        SentenceTransformerEmbedder()


def test_vector_store_embed_uses_passed_embedder(tmp_path):
    store = ChromaVectorStore(path=str(tmp_path), embedder=FakeEmbedder())
    other = FakeEmbedder(dimensions=8)
    embeddings = store.embed(["Paris is the capital of France."], embedder=other)
    assert embeddings.shape == (1, 8)
    assert embeddings[0, 0] == 1.0  # "paris"
