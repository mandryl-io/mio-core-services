import json
from unittest.mock import Mock

import pytest
from pipecat.frames.frames import LLMRunFrame
from pipecat.services.openai.realtime.events import parse_server_event

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
    pipeline._create_llm = lambda *args, **kwargs: None
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
    pipeline._create_llm = lambda *args, **kwargs: Mock()
    await pipeline.run_async()
    await pipeline._worker.handlers["on_pipeline_started"](pipeline._worker, None)
    assert pipeline.state is MioPipelineState.READY
    await pipeline.wait_until_ready(timeout=0.1)


async def test_client_connected_kicks_realtime_greeting(monkeypatch):
    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )
    pipeline = _pipeline()
    pipeline._create_llm = lambda *args, **kwargs: Mock()
    await pipeline.run_async()
    await pipeline._on_client_connected(None, None)
    frames = pipeline._worker.queued_frames
    assert len(frames) == 1
    assert isinstance(frames[0], LLMRunFrame)


async def test_pipeline_registers_medication_reminder_tool(monkeypatch):
    captured: dict = {}

    class CaptureContext:
        def __init__(self, messages, tools=None):
            captured["names"] = [tool.name for tool in (tools or [])]

        def set_tools(self, tools):
            captured["names"] = [tool.name for tool in (tools or [])]

    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )
    monkeypatch.setattr("mio_core_services.pipeline.LLMContext", CaptureContext)
    pipeline = _pipeline()
    pipeline._create_llm = lambda *args, **kwargs: Mock()
    await pipeline.run_async()
    assert "embed_knowledge" in captured["names"]
    assert "set_medication_reminder" in captured["names"]
    assert "name_person" in captured["names"]
    assert "who_is_facing" in captured["names"]


def test_session_updated_accepts_live_transcribe_languages():
    payload = {
        "type": "session.updated",
        "event_id": "event_test",
        "session": {
            "type": "realtime",
            "model": "gpt-realtime-2",
            "audio": {
                "input": {
                    "transcription": {
                        "model": "gpt-live-transcribe",
                        "language": None,
                        "languages": None,
                        "prompt": None,
                    }
                }
            },
        },
    }
    event = parse_server_event(json.dumps(payload))
    assert event.session.audio.input.transcription.model == "gpt-live-transcribe"


def test_realtime_uses_soft_server_turn_detection(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from pipecat.services.openai.realtime.events import SemanticTurnDetection

    from mio_core_services.pipeline import _OpenAIRealtimeLLMService

    pipeline = _pipeline()
    llm = pipeline._create_llm()
    assert isinstance(llm, _OpenAIRealtimeLLMService)
    turn = llm._settings.session_properties.audio.input.turn_detection
    assert isinstance(turn, SemanticTurnDetection)
    assert turn.eagerness == "low"
    assert turn.interrupt_response is False
    assert (
        llm._settings.session_properties.audio.input.noise_reduction.type
        == "far_field"
    )


async def test_soft_barge_in_skips_local_interruption(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    pipeline = _pipeline()
    llm = pipeline._create_llm()
    calls: list[str] = []

    async def record_broadcast(frame_type):
        calls.append(f"broadcast:{getattr(frame_type, '__name__', frame_type)}")

    async def record_truncate():
        calls.append("truncate")

    async def record_interrupt():
        calls.append("interrupt")

    monkeypatch.setattr(llm, "broadcast_frame", record_broadcast)
    monkeypatch.setattr(llm, "_truncate_current_audio_response", record_truncate)
    monkeypatch.setattr(llm, "broadcast_interruption", record_interrupt)

    await llm._handle_evt_speech_started(object())
    assert calls == ["broadcast:UserStartedSpeakingFrame"]
