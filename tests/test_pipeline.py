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
