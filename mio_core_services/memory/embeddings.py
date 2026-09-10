from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, PrivateAttr
from sentence_transformers import SentenceTransformer

from mio_core_services.constants import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
)


class MioTextEmbedder(BaseModel):
    """Interface for turning text into vectors.

    Implementations declare the width of the vectors they produce so stores can
    validate them against a collection's configured dimensions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dimensions: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return a (len(texts), dimensions) array, one row per input text."""


def _sentence_transformer(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


class SentenceTransformerEmbedder(MioTextEmbedder):
    """Local sentence-transformers backend."""

    model_name: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS

    _model: SentenceTransformer = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        model = _sentence_transformer(self.model_name)
        model_dims = model.get_sentence_embedding_dimension()
        if isinstance(model_dims, int) and model_dims != self.dimensions:
            raise ValueError(
                f"embedder model {self.model_name!r} produces {model_dims}-d "
                f"vectors, expected {self.dimensions}"
            )
        self._model = model

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        embeddings = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(embeddings, dtype=np.float32)
