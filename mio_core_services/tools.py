"""LLM tool schemas. Handlers are injected at composition time."""

from collections.abc import Awaitable, Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

FunctionHandler = Callable[[FunctionCallParams], Awaitable[None]]


class EmbedKnowledgeTool(FunctionSchema):
    """Schema for storing a fact. Pass ``RetrievalEngine.embed`` as the handler."""

    def __init__(self, handler: FunctionHandler) -> None:
        super().__init__(
            name="embed_knowledge",
            description=(
                "Embed text with the knowledge-base embedder and store it for later "
                "retrieval. Call this when the user asks you to remember a fact."
            ),
            properties={
                "text": {
                    "type": "string",
                    "description": "The fact or passage to embed and store.",
                },
                "id": {
                    "type": "string",
                    "description": "Optional stable document id. Reusing an id upserts.",
                },
            },
            required=["text"],
            handler=handler,
        )
