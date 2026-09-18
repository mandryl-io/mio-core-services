from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from mio_core_services.constants import DEFAULT_MEMORY_USER_ID

logger = logging.getLogger(__name__)

MEM0_CONTEXT_PREFIX = (
    "Relevant memories about this person. Do not read this list aloud; "
    "use it only so the conversation can feel continuous and informed."
)


class Mem0Client(Protocol):
    async def add(
        self, messages: list[dict[str, str]], user_id: str
    ) -> Any: ...

    async def search(self, query: str, filters: dict[str, str]) -> Any: ...


def memory_user_id(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    value = (env.get("MIO_MEMORY_USER_ID") or "").strip()
    return value or DEFAULT_MEMORY_USER_ID


def mem0_enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return bool((env.get("MEM0_API_KEY") or "").strip())


def create_mem0_client() -> Mem0Client | None:
    if not mem0_enabled():
        return None
    from mem0 import AsyncMemoryClient

    return AsyncMemoryClient()


class Mem0TurnMemory:
    """Store and recall Mem0 facts around a LiveKit user turn."""

    def __init__(
        self,
        client: Mem0Client | None,
        user_id: str | None = None,
    ) -> None:
        self._client = client
        self._user_id = user_id or memory_user_id()

    @classmethod
    def from_env(cls) -> Mem0TurnMemory:
        return cls(create_mem0_client())

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def user_id(self) -> str:
        return self._user_id

    async def remember_user_message(self, text: str) -> None:
        if self._client is None or not text.strip():
            return
        try:
            await self._client.add(
                [{"role": "user", "content": text}],
                user_id=self._user_id,
            )
        except Exception:
            logger.warning(
                "Failed to store user message in Mem0", exc_info=True
            )

    async def recall_context(self, query: str) -> str | None:
        if self._client is None or not query.strip():
            return None
        try:
            search_results = await self._client.search(
                query,
                filters={"user_id": self._user_id},
            )
        except Exception:
            logger.warning("Failed to search Mem0", exc_info=True)
            return None
        return format_mem0_results(search_results)


async def inject_mem0_turn(
    memory: Mem0TurnMemory,
    turn_ctx: Any,
    text: str,
) -> bool:
    """Persist the user turn and attach recalled Mem0 facts as a system message.

    Returns True when the chat context was changed and should be pushed back
    onto the agent with ``update_chat_ctx``.
    """
    if not text.strip() or not memory.enabled:
        return False
    await memory.remember_user_message(text)
    context = await memory.recall_context(text)
    if not context:
        return False
    turn_ctx.add_message(role="system", content=context)
    return True


def format_mem0_results(search_results: Any) -> str | None:
    parts: list[str] = []
    for result in _results_list(search_results):
        if not isinstance(result, dict):
            continue
        paragraph = result.get("memory") or result.get("text")
        if paragraph:
            parts.append(str(paragraph).strip())
    if not parts:
        return None
    bullets = "\n".join(f"- {part}" for part in parts)
    return f"{MEM0_CONTEXT_PREFIX}\n{bullets}"


def _results_list(search_results: Any) -> list[Any]:
    if search_results is None:
        return []
    if isinstance(search_results, dict):
        return list(search_results.get("results") or [])
    if isinstance(search_results, list):
        return search_results
    return []
