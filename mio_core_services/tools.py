from __future__ import annotations

from collections.abc import Awaitable, Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

FunctionHandler = Callable[[FunctionCallParams], Awaitable[None]]


class EmbedKnowledgeTool(FunctionSchema):
    """Schema for storing a core emotional experience. Pass ``RetrievalEngine.embed``."""

    def __init__(self, handler: FunctionHandler) -> None:
        super().__init__(
            name="embed_knowledge",
            description=(
                "Store a core emotional experience for later retrieval. Call only "
                "when the user is sharing a felt moment — grief, pride, "
                "loneliness, love, loss, or the like. Do not call for practical "
                "facts, small talk, preferences, tasks, or because they asked you "
                "to remember something mundane."
            ),
            properties={
                "text": {
                    "type": "string",
                    "description": (
                        "The core emotional experience, in the user's own words."
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


class SetMedicationReminderTool(FunctionSchema):
    """Schema for storing a Reminder. Pass ``MedicationReminders.set`` as the handler."""

    def __init__(self, handler: FunctionHandler) -> None:
        super().__init__(
            name="set_medication_reminder",
            description=(
                "Record a medication reminder. Call with whatever the user said. "
                "Omit fields they did not give. Do not invent a medication, time, "
                "or frequency. After the tool returns, say the returned sentence "
                "and wait; do not ask a second question."
            ),
            properties={
                "medication": {
                    "type": "string",
                    "description": "Named thing they take, e.g. blood pressure tablets.",
                },
                "when": {
                    "type": "string",
                    "description": "When to remind, as they said it.",
                },
                "frequency": {
                    "type": "string",
                    "description": "once, daily, weekly — only if they said it.",
                },
            },
            required=[],
            handler=handler,
        )


class NamePersonTool(FunctionSchema):
    """Bind a spoken name to a face. Pass ``PerceptionEngine.name_person``."""

    def __init__(self, handler: FunctionHandler) -> None:
        super().__init__(
            name="name_person",
            description=(
                "Store a name for a person facing the camera. Call this when "
                "someone tells you who an unrecognized person is. If only one "
                "unrecognized person is facing the camera, id can be omitted."
            ),
            properties={
                "name": {
                    "type": "string",
                    "description": "The person's name.",
                },
                "id": {
                    "type": "string",
                    "description": "Optional person id from the presence list.",
                },
            },
            required=["name"],
            handler=handler,
        )


class WhoIsFacingTool(FunctionSchema):
    """Current occupancy. Pass ``PerceptionEngine.who_is_facing``."""

    def __init__(self, handler: FunctionHandler) -> None:
        super().__init__(
            name="who_is_facing",
            description=(
                "Return who is facing the camera right now. Call this when you "
                "need to know who is there; do not guess."
            ),
            properties={},
            required=[],
            handler=handler,
        )
