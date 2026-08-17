from unittest.mock import Mock
from collections.abc import Sequence

import numpy as np
import pytest

from mio_core_services.memory.backends.chroma import ChromaVectorStore
from mio_core_services.memory.embeddings import SentenceTransformerEmbedder
from tests.test_chroma import MockEmbedder


def test_sentence_transformer_embedder_empty_texts(monkeypatch):
    monkeypatch.setattr(
        "mio_core_services.memory.embeddings._sentence_transformer",
        lambda model_name: Mock(),
    )
    embeddings = SentenceTransformerEmbedder().embed([])
    assert embeddings.shape == (0, 384)


def test_sentence_transformer_embedder_rejects_dimension_mismatch(monkeypatch):
    model = Mock()
    model.get_sentence_embedding_dimension.return_value = 128
    monkeypatch.setattr(
        "mio_core_services.memory.embeddings._sentence_transformer",
        lambda model_name: model,
    )
    with pytest.raises(ValueError, match="128-d"):
        SentenceTransformerEmbedder()


def test_vector_store_embed_uses_passed_embedder(tmp_path):
    store = ChromaVectorStore(path=str(tmp_path), embedder=MockEmbedder())
    other = MockEmbedder(dimensions=8)
    embeddings = store.embed(["Paris is the capital of France."], embedder=other)
    assert embeddings.shape == (1, 8)
    assert embeddings[0, 0] == 1.0  # "paris"
