"""Retrieve and attach knowledge as a Pipecat FrameProcessor."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams

from mio_core_services.memory.store import Document, MioVectorStore, SearchResult

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return " ".join(parts).strip()


def _latest_user_text(context: LLMContext) -> str | None:
    for message in reversed(context.get_messages()):
        if isinstance(message, dict) and message.get("role") == "user":
            text = _as_text(message.get("content"))
            if text:
                return text
    return None


class RetrievalEngine(FrameProcessor):
    """Retrieve knowledge after each user turn.

    Place this processor after the user aggregator and before the LLM.
    Retrieval is automatic. The model judges whether retrieved context is
    relevant. Register ``embed`` via ``EmbedKnowledgeTool`` at composition.
    """

    def __init__(
        self,
        vector_store: MioVectorStore,
        *,
        limit: int = 5,
        min_words: int = 4,
        min_chars: int = 16,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._vector_store = vector_store
        self._limit = limit
        self._min_words = min_words
        self._min_chars = min_chars
        self._last_query: str | None = None

    def is_retrievable(self, text: str) -> bool:
        """Return True when an utterance is complete enough to retrieve against."""
        stripped = text.strip()
        if len(stripped) < self._min_chars:
            return False
        return len(_WORD_RE.findall(stripped)) >= self._min_words

    async def embed(self, params: FunctionCallParams) -> None:
        text = str(params.arguments.get("text") or "").strip()
        if not text:
            await params.result_callback("No text provided.")
            return
        doc_id = str(params.arguments.get("id") or "").strip() or uuid.uuid4().hex
        try:
            await asyncio.to_thread(
                self._vector_store.add, [Document(id=doc_id, text=text)]
            )
        except Exception:
            logger.exception("retrieval: failed to embed and store document")
            await params.result_callback("Failed to store the document.")
            return
        await params.result_callback(f"Stored document {doc_id}.")

    async def attach_context(self, context: LLMContext) -> bool:
        """Retrieve for the latest user utterance and attach hits to context.

        Returns True when a new context message was added.
        """
        query = _latest_user_text(context)
        
        # self._last_query is set to the query of the last user utterance that we
        # performed a retrieval step for. This is so that if the retrieval engine
        # is called multiple times (e.g. perhaps there could be multiple LLMContextFrames)
        # in a pipeline, we don't want to perform the same retrieval step multiple times.
        if query is None or query == self._last_query:
            return False
        if not self.is_retrievable(query):
            logger.debug("retrieval: skipping low-quality utterance: %r", query)
            return False

        formatted = await self.retrieve(query)
        self._last_query = query
        if not formatted:
            return False

        context.add_message(
            {
                "role": "system",
                "content": _retrieved_knowledge_text(formatted),
            }
        )
        return True

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            await self.attach_context(frame.context)
        await self.push_frame(frame, direction)

    async def retrieve(self, query: str) -> str:
        try:
            results = await asyncio.to_thread(
                self._vector_store.search, query, self._limit
            )
        except Exception:
            logger.exception("retrieval: vector search failed")
            return ""
        logger.info("retrieval: retrieved %d document(s) for %r", len(results), query)
        return _format_results(results)


def _retrieved_knowledge_text(formatted: str) -> str:
    return (
        "Retrieved knowledge: use it when it is relevant to the user's "
        f"message and ignore it otherwise.\n\n{formatted}"
    )


def _format_results(results: list[SearchResult]) -> str:
    return "\n\n".join(
        f"[{index}] {result.document.text}"
        for index, result in enumerate(results, start=1)
    )
