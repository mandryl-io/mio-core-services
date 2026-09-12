from unittest.mock import Mock

import pytest
from pipecat.frames.frames import LLMRunFrame
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.turns.user_mute import AlwaysUserMuteStrategy
from pipecat.turns.user_start import WakePhraseUserTurnStartStrategy

from mio_core_services.constants import DEFAULT_WAKE_PHRASES, DEFAULT_WAKE_TIMEOUT_SECS
from mio_core_services.pipeline import MioPipeline, MioPipelineConfig, MioPipelineState
from tests.test_utils import MockTransport


def _pipeline() -> MioPipeline:
    return MioPipeline(
        MioPipelineConfig(
            vector_store=Mock(),
            transport=MockTransport(),
            reminder_db_path=":memory:",
        )
    )


def _stub_services(pipeline: MioPipeline) -> None:
    pipeline._create_stt = lambda *args, **kwargs: Mock()
    pipeline._create_llm = lambda *args, **kwargs: Mock()
    pipeline._create_tts = lambda *args, **kwargs: Mock()


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


def _patch_runner(monkeypatch) -> None:
    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr("mio_core_services.pipeline.SileroVADAnalyzer", Mock)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )


async def test_constructor_failure_sets_failed():
    pipeline = _pipeline()
    pipeline._create_stt = lambda *args, **kwargs: None
    await pipeline.run_async()
    assert pipeline.state is MioPipelineState.FAILED
    with pytest.raises(RuntimeError):
        await pipeline.wait_until_ready(timeout=0.1)


async def test_pipeline_started_sets_ready(monkeypatch):
    _patch_runner(monkeypatch)
    pipeline = _pipeline()
    _stub_services(pipeline)
    await pipeline.run_async()
    await pipeline._worker.handlers["on_pipeline_started"](pipeline._worker, None)
    assert pipeline.state is MioPipelineState.READY
    await pipeline.wait_until_ready(timeout=0.1)


async def test_client_connected_does_not_kick_greeting(monkeypatch):
    _patch_runner(monkeypatch)
    pipeline = _pipeline()
    _stub_services(pipeline)
    await pipeline.run_async()
    await pipeline._on_client_connected(None, None)
    assert pipeline._worker.queued_frames == []
    assert not any(
        isinstance(frame, LLMRunFrame) for frame in pipeline._worker.queued_frames
    )


async def test_pipeline_registers_medication_reminder_tool(monkeypatch):
    captured: dict = {}

    class CaptureContext:
        def __init__(self, messages=None, tools=None, tool_choice=None):
            captured["names"] = [tool.name for tool in (tools or [])]

        def set_tools(self, tools):
            captured["names"] = [tool.name for tool in (tools or [])]

    _patch_runner(monkeypatch)
    monkeypatch.setattr("mio_core_services.pipeline.LLMContext", CaptureContext)
    pipeline = _pipeline()
    _stub_services(pipeline)
    await pipeline.run_async()
    assert "embed_knowledge" in captured["names"]
    assert "set_medication_reminder" in captured["names"]
    assert "name_person" in captured["names"]
    assert "who_is_facing" in captured["names"]


def test_wake_phrase_and_half_duplex_mute(monkeypatch):
    monkeypatch.setattr("mio_core_services.pipeline.SileroVADAnalyzer", Mock)
    params = _pipeline()._user_aggregator_params()
    start = params.user_turn_strategies.start
    assert isinstance(start[0], WakePhraseUserTurnStartStrategy)
    assert start[0]._phrases == list(DEFAULT_WAKE_PHRASES)
    assert start[0]._timeout == DEFAULT_WAKE_TIMEOUT_SECS
    assert isinstance(params.user_mute_strategies[0], AlwaysUserMuteStrategy)


def test_cascade_uses_openai_stt_llm_tts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pipeline = _pipeline()
    assert isinstance(pipeline._create_stt(), OpenAISTTService)
    assert isinstance(pipeline._create_llm(), OpenAILLMService)
    assert isinstance(pipeline._create_tts(), OpenAITTSService)
