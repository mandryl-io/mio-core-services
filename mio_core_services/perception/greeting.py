from __future__ import annotations

from mio_core_services.constants import DEFAULT_BOT_NAME


def join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def spoken_greeting(initial_message: str, names: list[str]) -> str:
    """Opening line. Names the known faces only; unnamed people are omitted."""
    if not names:
        return initial_message
    return f"Hi, {join_names(names)}. I'm {DEFAULT_BOT_NAME}. How are you today?"


GREETING_PREFIX = (
    "Greet the user by saying exactly this, then wait for them to speak: "
)


def greeting_developer_message(spoken: str) -> dict[str, str]:
    return {"role": "developer", "content": f"{GREETING_PREFIX}{spoken}"}


def is_greeting_message(message: object) -> bool:
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith(GREETING_PREFIX)
