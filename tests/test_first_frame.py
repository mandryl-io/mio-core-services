import asyncio

from pipecat.frames.frames import InputImageRawFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection

from mio_core_services.first_frame import FirstFrameGate


def _gate(**kwargs) -> FirstFrameGate:
    gate = FirstFrameGate(**kwargs)
    gate.pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        gate.pushed.append(frame)

    gate.push_frame = capture
    return gate


async def test_skipped_wait_returns_immediately_without_a_frame():
    gate = _gate(skipped=True)

    arrived = await gate.wait(timeout=5)

    assert arrived is False


async def test_wait_returns_true_after_matching_frame():
    gate = _gate()
    image = InputImageRawFrame(image=b"\x00", size=(1, 1), format="RGB")

    task = asyncio.create_task(gate.wait(timeout=1))
    await gate.process_frame(image, FrameDirection.DOWNSTREAM)

    assert await task is True
    assert image in gate.pushed


async def test_wait_times_out_without_a_matching_frame():
    gate = _gate()

    arrived = await gate.wait(timeout=0.05)

    assert arrived is False


async def test_non_matching_frames_pass_through_without_releasing_wait():
    gate = _gate()
    text = TextFrame(text="hello")

    task = asyncio.create_task(gate.wait(timeout=0.05))
    await gate.process_frame(text, FrameDirection.DOWNSTREAM)
    arrived = await task

    assert arrived is False
    assert text in gate.pushed
