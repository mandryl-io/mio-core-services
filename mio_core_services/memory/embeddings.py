from abc import abstractmethod
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
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


class SentenceTransformerEmbedder(MioTextEmbedder):
    """Local sentence-transformers backend."""

    model_name: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS

    _model: SentenceTransformer

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        embeddings = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(embeddings, dtype=np.float32)
