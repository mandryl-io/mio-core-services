import asyncio
import threading
from typing import Any
from unittest.mock import Mock

import numpy as np
from pipecat.frames.frames import InputImageRawFrame, InputTextRawFrame, TextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from mio_core_services.perception.backend import DetectedFace
from mio_core_services.perception.engine import PerceptionEngine
from mio_core_services.perception.occupancy import PRESENCE_PREFIX
from mio_core_services.perception.store import FaceStore


class FakeFaceBackend:
    def __init__(self) -> None:
        self.frames: list[list[DetectedFace]] = []

    def detect(self, image, *, size, format=None) -> list[DetectedFace]:
        if self.frames:
            return self.frames.pop(0)
        return []


def _face(*values: float, facing: bool = True) -> DetectedFace:
    return DetectedFace(
        embedding=np.asarray(values, dtype=np.float32),
        facing=facing,
    )


def _engine(backend: FakeFaceBackend | None = None):
    backend = backend or FakeFaceBackend()
    context = LLMContext(messages=[{"role": "user", "content": "hello there friend"}])
    engine = PerceptionEngine(backend, FaceStore(), context)
    engine.pushed: list[Any] = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        engine.pushed.append(frame)

    engine.push_frame = capture
    return engine, backend, context


def _presence_messages(context: LLMContext) -> list[str]:
    return [
        message["content"]
        for message in context.get_messages()
        if isinstance(message, dict)
        and isinstance(message.get("content"), str)
        and message["content"].startswith(PRESENCE_PREFIX)
    ]


async def _wait_detect(engine: PerceptionEngine) -> None:
    task = getattr(engine, "_detect_task", None)
    if task is not None:
        await task


async def test_slow_detect_does_not_block_process_frame():
    release = threading.Event()

    class BlockingBackend:
        def detect(self, image, *, size, format=None) -> list[DetectedFace]:
            release.wait(timeout=5)
            return []

    engine, _backend, _context = _engine(BlockingBackend())
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")
    task = asyncio.create_task(
        engine.process_frame(image, FrameDirection.DOWNSTREAM)
    )
    try:
        done, _pending = await asyncio.wait({task}, timeout=0.2)
        assert task in done
    finally:
        release.set()
        await task
        await _wait_detect(engine)


async def test_image_frames_are_not_pushed_downstream():
    engine, backend, context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])

    await engine.process_frame(
        InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB"),
        FrameDirection.DOWNSTREAM,
    )
    await _wait_detect(engine)

    assert not any(isinstance(frame, InputImageRawFrame) for frame in engine.pushed)
    assert any("unrecognized person" in text for text in _presence_messages(context))


async def test_user_text_still_passes_through_without_llm_run():
    engine, _backend, _context = _engine()
    text = TextFrame(text="I miss her so much")

    await engine.process_frame(text, FrameDirection.DOWNSTREAM)

    assert text in engine.pushed


async def test_leave_removes_presence_message():
    engine, backend, context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])
    backend.frames.append([])
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")

    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    await _wait_detect(engine)
    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    await _wait_detect(engine)

    assert _presence_messages(context) == []


async def test_name_person_binds_the_unnamed_occupant():
    engine, backend, context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])
    captured: list[Any] = []

    async def result_callback(result: Any, *, properties=None) -> None:
        captured.append(result)

    await engine.process_frame(
        InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB"),
        FrameDirection.DOWNSTREAM,
    )
    await _wait_detect(engine)
    await engine.name_person(
        Mock(arguments={"name": "Sarah"}, result_callback=result_callback)
    )

    assert captured[0].startswith("Named")
    assert any("Sarah" in text for text in _presence_messages(context))


async def test_wait_for_facing_returns_once_someone_is_present():
    engine, backend, _context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")

    wait = asyncio.create_task(engine.wait_for_facing(timeout=1))
    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    snapshot = await wait

    assert snapshot.occupants
    assert snapshot.occupants[0].name is None


async def test_wait_for_facing_times_out_when_the_frame_is_empty():
    engine, backend, _context = _engine()
    backend.frames.append([])
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")

    wait = asyncio.create_task(engine.wait_for_facing(timeout=0.05))
    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    snapshot = await wait

    assert snapshot.occupants == []


async def test_who_is_facing_returns_current_occupants():
    engine, backend, _context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])
    captured: list[Any] = []

    async def result_callback(result: Any, *, properties=None) -> None:
        captured.append(result)

    await engine.process_frame(
        InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB"),
        FrameDirection.DOWNSTREAM,
    )
    await _wait_detect(engine)
    await engine.who_is_facing(Mock(arguments={}, result_callback=result_callback))

    assert "new_this_session" in captured[0]


async def test_single_occupant_is_named_from_spoken_correction():
    engine, backend, context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")

    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    await _wait_detect(engine)
    await engine.process_frame(
        InputTextRawFrame(text="I'm Sarah"),
        FrameDirection.DOWNSTREAM,
    )

    assert any("Sarah" in text for text in _presence_messages(context))
    assert engine.occupancy.snapshot.occupants[0].name == "Sarah"


async def test_spoken_correction_is_ignored_when_several_people_are_facing():
    engine, backend, context = _engine()
    backend.frames.append([_face(1, 0, 0, 0), _face(0, 1, 0, 0)])
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")

    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    await _wait_detect(engine)
    await engine.process_frame(
        InputTextRawFrame(text="I'm Sarah"),
        FrameDirection.DOWNSTREAM,
    )

    assert all("Sarah" not in text for text in _presence_messages(context))


async def test_single_occupant_can_correct_a_matched_name():
    engine, backend, context = _engine()
    backend.frames.append([_face(1, 0, 0, 0)])
    image = InputImageRawFrame(image=b"\x00\x00\x00", size=(1, 1), format="RGB")

    await engine.process_frame(image, FrameDirection.DOWNSTREAM)
    await _wait_detect(engine)
    engine.apply_spoken_name("I'm Dillon")
    engine.apply_spoken_name("I'm not Dillon, I'm Sarah")

    assert engine.occupancy.snapshot.occupants[0].name == "Sarah"
    assert any("Sarah" in text for text in _presence_messages(context))
