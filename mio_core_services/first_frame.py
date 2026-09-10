from __future__ import annotations

import asyncio

from pipecat.frames.frames import Frame, InputImageRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class FirstFrameGate(FrameProcessor):
    """Wait for the first frame of a given type, or time out.

    Passes every frame through. If ``skipped`` is true (no video path),
    ``wait`` returns False immediately so callers can proceed without a frame.
    """

    def __init__(
        self,
        frame_type: type[Frame] = InputImageRawFrame,
        *,
        skipped: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._frame_type = frame_type
        self._skipped = skipped
        self._arrived = asyncio.Event()

    async def wait(self, timeout: float) -> bool:
        if self._skipped:
            return False
        try:
            await asyncio.wait_for(self._arrived.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, self._frame_type):
            self._arrived.set()
        await self.push_frame(frame, direction)
