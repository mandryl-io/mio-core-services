from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, PrivateAttr
from sentence_transformers import SentenceTransformer

_MODEL_CACHE: dict[str, Any] = {}

DEFAULT_EMBEDDING_MODEL = "thenlper/gte-small"
DEFAULT_EMBEDDING_DIMENSIONS = 384


def _sentence_transformer(model_name: str) -> Any:
    model = _MODEL_CACHE.get(model_name)
    if model is None:
        model = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = model
    return model


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
    """Local sentence-transformers backend with a process-wide model cache."""

    model_name: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS

    _model: Any = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        self._model = _sentence_transformer(self.model_name)
        model_dimensions = int(self._model.get_sentence_embedding_dimension())
        if model_dimensions != self.dimensions:
            raise ValueError(
                f"{self.model_name} produces {model_dimensions}-d vectors, "
                f"but dimensions={self.dimensions}"
            )

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        embeddings = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(embeddings, dtype=np.float32)
