from types import SimpleNamespace
from typing import Any

from pipecat.frames.frames import LLMContextFrame, StartFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from mio_core_services.retrieval_engine import RetrievalEngine
from mio_core_services.vector_store.base import Document, SearchResult


class FakeVectorStore:
    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = results or []
        self.queries: list[tuple[str, int]] = []
        self.added: list[Document] = []
        self.fail = False

    def add(self, documents: list[Document]) -> None:
        if self.fail:
            raise RuntimeError("add failed")
        self.added.extend(documents)

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.queries.append((query, limit))
        if self.fail:
            raise RuntimeError("search failed")
        return self.results[:limit]


def _result(text: str, doc_id: str = "doc-1") -> SearchResult:
    return SearchResult(document=Document(id=doc_id, text=text), score=0.9)


async def test_attach_context_skips_low_quality_utterances():
    store = FakeVectorStore([_result("Refunds are issued within 14 days.")])
    processor = RetrievalEngine(store)
    context = LLMContext(messages=[{"role": "user", "content": "um yeah"}])

    injected = await processor.attach_context(context)

    assert injected is False
    assert store.queries == []
    assert context.get_messages() == [{"role": "user", "content": "um yeah"}]


async def test_attach_context_adds_retrieved_context():
    store = FakeVectorStore([_result("Enterprise refunds take 14 days.")])
    processor = RetrievalEngine(store)
    context = LLMContext(
        messages=[
            {
                "role": "user",
                "content": "What is the refund policy for enterprise plans?",
            }
        ]
    )

    injected = await processor.attach_context(context)

    assert injected is True
    assert store.queries == [
        ("What is the refund policy for enterprise plans?", 5)
    ]
    messages = context.get_messages()
    assert messages[-1]["role"] == "system"
    assert "Enterprise refunds take 14 days." in messages[-1]["content"]


async def test_attach_context_does_not_repeat_for_the_same_utterance():
    store = FakeVectorStore([_result("Enterprise refunds take 14 days.")])
    processor = RetrievalEngine(store)
    context = LLMContext(
        messages=[
            {
                "role": "user",
                "content": "What is the refund policy for enterprise plans?",
            }
        ]
    )

    assert await processor.attach_context(context) is True
    assert await processor.attach_context(context) is False
    assert len(store.queries) == 1


async def test_attach_context_skips_empty_search_results():
    store = FakeVectorStore([])
    processor = RetrievalEngine(store)
    context = LLMContext(
        messages=[
            {
                "role": "user",
                "content": "What is the refund policy for enterprise plans?",
            }
        ]
    )

    injected = await processor.attach_context(context)

    assert injected is False
    assert len(store.queries) == 1
    assert all(message.get("role") != "system" for message in context.get_messages())


async def test_embed_stores_document():
    store = FakeVectorStore()
    processor = RetrievalEngine(store)
    captured: list[Any] = []

    async def result_callback(result: Any, *, properties=None) -> None:
        captured.append(result)

    params = SimpleNamespace(
        arguments={"text": "Q3 revenue was $12M.", "id": "q3"},
        result_callback=result_callback,
    )

    await processor.embed(params)

    assert len(store.added) == 1
    assert store.added[0].id == "q3"
    assert store.added[0].text == "Q3 revenue was $12M."
    assert captured == ["Stored document q3."]


async def test_embed_rejects_empty_text():
    store = FakeVectorStore()
    processor = RetrievalEngine(store)
    captured: list[Any] = []

    async def result_callback(result: Any, *, properties=None) -> None:
        captured.append(result)

    await processor.embed(
        SimpleNamespace(arguments={"text": "  "}, result_callback=result_callback)
    )

    assert store.added == []
    assert captured == ["No text provided."]


async def test_process_frame_injects_on_downstream_context():
    store = FakeVectorStore([_result("Enterprise refunds take 14 days.")])
    processor = RetrievalEngine(store, enable_direct_mode=True)
    context = LLMContext(
        messages=[
            {
                "role": "user",
                "content": "What is the refund policy for enterprise plans?",
            }
        ]
    )

    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(
        LLMContextFrame(context=context), FrameDirection.DOWNSTREAM
    )

    assert any(
        message.get("role") == "system"
        and "Enterprise refunds take 14 days." in message.get("content", "")
        for message in context.get_messages()
    )


async def test_process_frame_ignores_upstream_context():
    store = FakeVectorStore([_result("Enterprise refunds take 14 days.")])
    processor = RetrievalEngine(store, enable_direct_mode=True)
    context = LLMContext(
        messages=[
            {
                "role": "user",
                "content": "What is the refund policy for enterprise plans?",
            }
        ]
    )

    await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(
        LLMContextFrame(context=context), FrameDirection.UPSTREAM
    )

    assert store.queries == []
