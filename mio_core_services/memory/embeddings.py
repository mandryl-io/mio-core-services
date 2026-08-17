from abc import abstractmethod
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict


class MioTextEmbedder(BaseModel):
    """Interface for turning text into vectors.

    Implementations declare the width of the vectors they produce so stores can
    validate them against a collection's configured dimensions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dimensions: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
