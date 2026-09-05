"""LLM tool schemas. Handlers are injected at composition time."""

from collections.abc import Awaitable, Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

FunctionHandler = Callable[[FunctionCallParams], Awaitable[None]]


class EmbedKnowledgeTool(FunctionSchema):
    """Schema for storing a lasting memory. Pass ``RetrievalEngine.embed`` as the handler."""

    def __init__(self, handler: FunctionHandler) -> None:
        super().__init__(
            name="embed_knowledge",
            description=(
                "Save a lasting memory about the user for later conversations. Call this "
                "on your own whenever they share something personal worth knowing — "
                "emotional or life stories, people and places that matter to them, "
                "preferences, routines, hobbies, or fun facts about themselves. Do not "
                "wait for them to ask you to remember. Skip small talk and one-off "
                "remarks that would not matter next time you speak."
            ),
            properties={
                "text": {
                    "type": "string",
                    "description": (
                        "A concise, self-contained memory of what they shared, written "
                        "so it is useful without the rest of the conversation."
                    ),
                },
                "id": {
                    "type": "string",
                    "description": "Optional stable document id. Reusing an id upserts.",
                },
            },
            required=["text"],
            handler=handler,
        )
