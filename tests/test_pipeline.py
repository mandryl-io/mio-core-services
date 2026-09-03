from unittest.mock import Mock

import pytest

from mio_core_services.pipeline import MioPipeline, MioPipelineConfig, MioPipelineState
from tests.test_utils import MockTransport


def _pipeline() -> MioPipeline:
    return MioPipeline(
        MioPipelineConfig(
            vector_store=Mock(),
            transport=MockTransport(),
            vad_analyzer=Mock(),
            user_turn_strategies=Mock(),
        )
    )


class MockWorker:
    def __init__(self, *args, **kwargs) -> None:
        self.handlers = {}
        self.queued_frames = []

    def event_handler(self, name: str):
        def decorator(fn):
            self.handlers[name] = fn
            return fn

        return decorator

    async def queue_frames(self, frames) -> None:
        self.queued_frames.extend(frames)


class MockRunner:
    async def add_workers(self, *args, **kwargs) -> None:
        return None

    async def run(self) -> None:
        return None


async def test_constructor_failure_sets_failed():
    pipeline = _pipeline()
    pipeline._create_stt = lambda: None
    await pipeline.run_async()
    assert pipeline.state is MioPipelineState.FAILED
    with pytest.raises(RuntimeError):
        await pipeline.wait_until_ready(timeout=0.1)


async def test_pipeline_started_sets_ready(monkeypatch):
    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )
    pipeline = _pipeline()
    pipeline._create_stt = lambda: Mock()
    pipeline._create_llm = lambda embed_tool_name=None: Mock()
    pipeline._create_tts = lambda: Mock()
    await pipeline.run_async()
    await pipeline._worker.handlers["on_pipeline_started"](pipeline._worker, None)
    assert pipeline.state is MioPipelineState.READY
    await pipeline.wait_until_ready(timeout=0.1)


async def test_client_connected_speaks_greeting_without_llm(monkeypatch):
    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )
    pipeline = _pipeline()
    pipeline._create_stt = lambda: Mock()
    pipeline._create_llm = lambda embed_tool_name=None: Mock()
    pipeline._create_tts = lambda: Mock()
    await pipeline.run_async()
    await pipeline._on_client_connected(None, None)
    frames = pipeline._worker.queued_frames
    assert len(frames) == 1
    assert frames[0].text == pipeline.pipeline_config.initial_message
