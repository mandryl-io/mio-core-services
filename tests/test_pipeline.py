import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from pipecat.frames.frames import LLMRunFrame
from pipecat.services.openai.realtime.events import parse_server_event

from mio_core_services.perception.greeting import is_greeting_message
from mio_core_services.perception.occupancy import OccupancySnapshot, Occupant
from mio_core_services.pipeline import MioPipeline, MioPipelineConfig, MioPipelineState
from tests.test_utils import MockTransport


def _pipeline() -> MioPipeline:
    return MioPipeline(
        MioPipelineConfig(
            vector_store=Mock(),
            transport=MockTransport(),
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
    greetings = [
        message
        for message in pipeline._context.get_messages()
        if is_greeting_message(message)
    ]
    assert greetings
    assert "I'm Mio" in greetings[0]["content"]
    assert pipeline._greeting_task is None


def _named_snapshot(*names: str) -> OccupancySnapshot:
    return OccupancySnapshot(
        occupants=[
            Occupant(
                person_id=name.lower(),
                embedding=np.zeros(4, dtype=np.float32),
                name=name,
            )
            for name in names
        ]
    )


async def test_video_greeting_names_people_facing_the_camera(monkeypatch):
    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )
    transport = MockTransport()
    transport._params = SimpleNamespace(video_in_enabled=True)
    pipeline = MioPipeline(
        MioPipelineConfig(vector_store=Mock(), transport=transport)
    )
    pipeline._create_llm = lambda *args, **kwargs: Mock()
    await pipeline.run_async()

    async def first_frame_arrives(timeout):
        return True

    async def dillon_is_facing(timeout):
        return _named_snapshot("Dillon")

    pipeline._first_frame.wait = first_frame_arrives
    pipeline._perception.wait_for_facing = dillon_is_facing
    await pipeline._on_client_connected(None, None)
    await pipeline._greeting_task

    greetings = [
        message
        for message in pipeline._context.get_messages()
        if is_greeting_message(message)
    ]
    assert "Hi, Dillon." in greetings[0]["content"]
    assert isinstance(pipeline._worker.queued_frames[0], LLMRunFrame)


async def test_video_greeting_falls_back_when_no_frame_arrives(monkeypatch):
    monkeypatch.setattr("mio_core_services.pipeline.PipelineWorker", MockWorker)
    monkeypatch.setattr("mio_core_services.pipeline.WorkerRunner", MockRunner)
    monkeypatch.setattr(
        "mio_core_services.pipeline.LLMContextAggregatorPair",
        lambda *args, **kwargs: (Mock(), Mock()),
    )
    transport = MockTransport()
    transport._params = SimpleNamespace(video_in_enabled=True)
    pipeline = MioPipeline(
        MioPipelineConfig(
            vector_store=Mock(),
            transport=transport,
            first_frame_timeout=0.01,
            face_window=0.01,
        )
    )
    pipeline._create_llm = lambda *args, **kwargs: Mock()
    await pipeline.run_async()
    await pipeline._on_client_connected(None, None)
    await pipeline._greeting_task

    greetings = [
        message
        for message in pipeline._context.get_messages()
        if is_greeting_message(message)
    ]
    assert "Hi, I'm Mio." in greetings[0]["content"]
    assert "Dillon" not in greetings[0]["content"]


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
