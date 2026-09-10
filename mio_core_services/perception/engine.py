from __future__ import annotations

import asyncio
import json
import logging

from pipecat.frames.frames import (
    Frame,
    InputImageRawFrame,
    InputTextRawFrame,
    TranscriptionFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams

from mio_core_services.perception.backend import FaceBackend
from mio_core_services.perception.identity import parse_spoken_name
from mio_core_services.perception.occupancy import (
    PRESENCE_PREFIX,
    Occupancy,
    OccupancySnapshot,
)
from mio_core_services.perception.store import FaceStore

logger = logging.getLogger(__name__)


class PerceptionEngine(FrameProcessor):
    """Run a FaceBackend on camera frames and keep occupancy on LLMContext.

    Place on the camera input path. Image frames are swallowed so pixels never
    reach the LLM. No LLMRunFrame — Mio may mention who is facing the camera
    on a turn it was already going to take.
    """

    def __init__(
        self,
        backend: FaceBackend,
        store: FaceStore,
        context: LLMContext,
        *,
        occupancy: Occupancy | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._backend = backend
        self._store = store
        self._context = context
        self._occupancy = occupancy or Occupancy(store)
        self._busy = False
        self._detect_task: asyncio.Task | None = None
        self._facing = asyncio.Event()

    @property
    def occupancy(self) -> Occupancy:
        return self._occupancy

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputImageRawFrame):
            if not self._busy:
                self._busy = True
                self._detect_task = asyncio.create_task(self._handle_image(frame))
            return
        if isinstance(frame, (InputTextRawFrame, TranscriptionFrame)):
            self.apply_spoken_name(frame.text)
        await self.push_frame(frame, direction)

    async def _handle_image(self, frame: InputImageRawFrame) -> None:
        try:
            detections = await asyncio.to_thread(
                self._backend.detect,
                frame.image,
                size=frame.size,
                format=frame.format,
            )
            snapshot = self._occupancy.apply(detections)
            if snapshot.occupants:
                self._facing.set()
            else:
                self._facing.clear()
            self._sync_presence(snapshot.presence_text())
        except Exception:
            logger.exception("perception: face detection failed")
        finally:
            self._busy = False

    async def wait_for_facing(self, timeout: float) -> OccupancySnapshot:
        if self._occupancy.snapshot.occupants:
            return self._occupancy.snapshot
        try:
            await asyncio.wait_for(self._facing.wait(), timeout=timeout)
        except TimeoutError:
            pass
        return self._occupancy.snapshot

    async def cleanup(self):
        if self._detect_task is not None:
            self._detect_task.cancel()
            try:
                await self._detect_task
            except asyncio.CancelledError:
                pass
            self._detect_task = None
        await super().cleanup()

    def _sync_presence(self, text: str | None) -> None:
        messages = [
            message
            for message in self._context.get_messages()
            if not _is_presence_message(message)
        ]
        if text:
            messages.append({"role": "system", "content": text})
        self._context.set_messages(messages)

    async def name_person(self, params: FunctionCallParams) -> None:
        name = str(params.arguments.get("name") or "").strip()
        person_id = str(params.arguments.get("id") or "").strip()
        if not name:
            await params.result_callback("No name provided.")
            return
        if not person_id:
            unnamed = [
                occupant
                for occupant in self._occupancy.snapshot.occupants
                if not occupant.name
            ]
            if len(unnamed) == 1:
                person_id = unnamed[0].person_id
            elif not unnamed:
                await params.result_callback("No unrecognized person is facing the camera.")
                return
            else:
                await params.result_callback(
                    "Several unrecognized people are facing the camera; pass id."
                )
                return
        occupant = self._occupancy.set_name(person_id, name)
        if occupant is None and self._store.get(person_id) is None:
            await params.result_callback(f"Unknown person id {person_id}.")
            return
        self._sync_presence(self._occupancy.snapshot.presence_text())
        await params.result_callback(f"Named {person_id} {name}.")

    def apply_spoken_name(self, text: str) -> bool:
        spoken = parse_spoken_name(text)
        if spoken is None or not spoken.name:
            return False
        occupants = self._occupancy.snapshot.occupants
        if len(occupants) != 1:
            return False
        occupant = occupants[0]
        if (
            spoken.rejected
            and occupant.name
            and occupant.name.lower() != spoken.rejected.lower()
        ):
            return False
        if occupant.name and occupant.name.lower() == spoken.name.lower():
            return False
        self._occupancy.set_name(occupant.person_id, spoken.name)
        self._sync_presence(self._occupancy.snapshot.presence_text())
        return True

    async def who_is_facing(self, params: FunctionCallParams) -> None:
        await params.result_callback(
            json.dumps(self._occupancy.snapshot.as_dicts())
        )


def _is_presence_message(message: object) -> bool:
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith(PRESENCE_PREFIX)
