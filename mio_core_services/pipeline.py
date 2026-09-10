"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pipecat.frames.frames import InputTextRawFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    AudioOutput,
    ConversationItem,
    ConversationItemCreateEvent,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    ItemContent,
    SemanticTurnDetection,
    SessionProperties,
)
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from mio_core_services.constants import (
    DEFAULT_FACE_WINDOW_SECS,
    DEFAULT_FIRST_FRAME_TIMEOUT_SECS,
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_LLM_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TRANSCRIPTION_MODEL,
    DEFAULT_TRANSPORT_PARAMS,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.first_frame import FirstFrameGate
from mio_core_services.memory import MioVectorStore, RetrievalEngine
from mio_core_services.perception import FaceStore, PerceptionEngine
from mio_core_services.perception.backend import FaceBackend, NoOpFaceBackend
from mio_core_services.perception.greeting import (
    greeting_developer_message,
    is_greeting_message,
    spoken_greeting,
)
from mio_core_services.tools import EmbedKnowledgeTool, NamePersonTool, WhoIsFacingTool
from mio_core_services.utils import TerminalDashboard

logger = logging.getLogger(__name__)

# Pipecat's InputAudioTranscription.__init__ only accepts model/language/prompt.
# gpt-live-transcribe session echoes also include `languages`, which crashes
# parse_server_event on session.updated.
_original_input_audio_transcription_init = InputAudioTranscription.__init__


def _init_input_audio_transcription(self, *args, **kwargs) -> None:
    kwargs.pop("languages", None)
    _original_input_audio_transcription_init(self, *args, **kwargs)


InputAudioTranscription.__init__ = _init_input_audio_transcription

# Text-mode evals send RTVI send-text, which only interrupts a Realtime session
# (pipecat-ai/pipecat#3829). Also inject InputTextRawFrame so we can create a
# conversation item and kick response.create.
_original_rtvi_handle_send_text = RTVIProcessor._handle_send_text


async def _handle_send_text_for_realtime(self, data) -> None:
    await _original_rtvi_handle_send_text(self, data)
    opts = data.options
    if opts is not None and opts.run_immediately is False:
        return
    await self.push_frame(InputTextRawFrame(text=data.content))


RTVIProcessor._handle_send_text = _handle_send_text_for_realtime


class _OpenAIRealtimeLLMService(OpenAIRealtimeLLMService):
    """Realtime service that can take typed eval turns, not only mic audio."""

    async def process_frame(self, frame, direction: FrameDirection):
        if isinstance(frame, InputTextRawFrame):
            await self._send_user_text(frame.text)
        await super().process_frame(frame, direction)

    async def _send_user_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        item = ConversationItem(
            type="message",
            role="user",
            content=[ItemContent(type="input_text", text=text)],
        )
        event = ConversationItemCreateEvent(item=item)
        self._messages_added_manually[event.item.id] = True
        await self.send_client_event(event)
        await self._create_response()


@dataclass
class MioPipelineConfig:
    vector_store: MioVectorStore
    llm_model: str = DEFAULT_LLM_MODEL
    system_instruction: str = DEFAULT_SYSTEM_PROMPT
    transport: BaseTransport | None = None
    # Spoken on connect by kicking the realtime model so the greeting
    # is the first assistant turn.
    initial_message: str | None = DEFAULT_INITIAL_MESSAGE
    face_store: FaceStore | None = None
    face_backend: FaceBackend | None = None
    first_frame_timeout: float = DEFAULT_FIRST_FRAME_TIMEOUT_SECS
    face_window: float = DEFAULT_FACE_WINDOW_SECS


class MioPipelineState(StrEnum):
    IDLE = "idle"
    LOADING = "loading"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    FINISHED = "finished"


class MioPipeline:
    """Voice pipeline over a single OpenAI Realtime connection.

    Requires a ``MioPipelineConfig`` with a ``vector_store``. Other config
    fields default (WebRTC transport, gpt-realtime-2 with gpt-live-transcribe
    input transcription, system prompt). Requires ``OPENAI_API_KEY``.
    """

    def __init__(self, pipeline_config: MioPipelineConfig) -> None:
        self.pipeline_config = pipeline_config
        self._transport: BaseTransport | None = self.pipeline_config.transport
        self._llm_model: str = self.pipeline_config.llm_model
        self._system_instruction: str = self.pipeline_config.system_instruction
        self._worker: PipelineWorker | None = None
        self._llm: OpenAIRealtimeLLMService | None = None
        self._state = MioPipelineState.IDLE
        self._loading_service: Literal["llm"] | None = None
        self._ready_event = asyncio.Event()
        self._context: LLMContext | None = None
        self._perception: PerceptionEngine | None = None
        self._first_frame: FirstFrameGate | None = None
        self._greeting_task: asyncio.Task | None = None

    @property
    def state(self) -> MioPipelineState:
        return self._state

    @property
    def loading_service(self) -> Literal["llm"] | None:
        return self._loading_service

    def _set_state(self, state: MioPipelineState) -> None:
        self._state = state
        if state is not MioPipelineState.LOADING:
            self._loading_service = None
        if state in (
            MioPipelineState.READY,
            MioPipelineState.FAILED,
            MioPipelineState.FINISHED,
        ):
            self._ready_event.set()

    async def wait_until_ready(self, timeout: float | None = None) -> None:
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(
                f"timed out waiting for pipeline to become ready (state={self._state.value})"
            ) from exc
        if self._state is MioPipelineState.READY:
            return
        raise RuntimeError(
            f"pipeline failed to become ready (state={self._state.value})"
        )

    def _openai_api_key(self) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        return api_key

    def _create_llm(
        self,
        embed_tool_name: str | None = None,
        extra_instruction: str = "",
    ) -> OpenAIRealtimeLLMService | None:
        try:
            api_key = self._openai_api_key()
            system_instruction = self._system_instruction
            if embed_tool_name is not None:
                system_instruction += (
                    " Retrieved knowledge may be attached to each turn; use it when "
                    "it is relevant and ignore it otherwise. "
                    f"Call {embed_tool_name} when the user asks you to remember a fact."
                )
            if extra_instruction:
                system_instruction += extra_instruction
            return _OpenAIRealtimeLLMService(
                api_key=api_key,
                settings=OpenAIRealtimeLLMService.Settings(
                    model=self._llm_model,
                    system_instruction=system_instruction,
                    session_properties=SessionProperties(
                        audio=AudioConfiguration(
                            input=AudioInput(
                                transcription=InputAudioTranscription(
                                    model=DEFAULT_TRANSCRIPTION_MODEL,
                                ),
                                turn_detection=SemanticTurnDetection(),
                                noise_reduction=InputAudioNoiseReduction(
                                    type="near_field"
                                ),
                            ),
                            output=AudioOutput(voice=DEFAULT_TTS_VOICE),
                        ),
                    ),
                ),
            )
        except Exception:
            logger.exception("MioPipeline: failed to start OpenAI Realtime service")
            return None

    def _create_retrieval_engine(self) -> RetrievalEngine:
        return RetrievalEngine(self.pipeline_config.vector_store)

    def _video_in_enabled(self) -> bool:
        params = getattr(self._transport, "_params", None)
        return bool(getattr(params, "video_in_enabled", False))

    async def _queue_greeting(self, names: list[str]) -> None:
        if self._worker is None or self._context is None:
            return
        initial = self.pipeline_config.initial_message
        if not initial:
            return
        spoken = spoken_greeting(initial, names)
        messages = [
            message
            for message in self._context.get_messages()
            if not is_greeting_message(message)
        ]
        messages.insert(0, greeting_developer_message(spoken))
        self._context.set_messages(messages)
        await self._worker.queue_frames([LLMRunFrame()])

    async def _greet_after_perception(self) -> None:
        names: list[str] = []
        gate = self._first_frame
        perception = self._perception
        if (
            gate is not None
            and perception is not None
            and await gate.wait(self.pipeline_config.first_frame_timeout)
        ):
            snapshot = await perception.wait_for_facing(
                self.pipeline_config.face_window
            )
            names = snapshot.names()
        await self._queue_greeting(names)

    async def _on_client_connected(self, transport, client) -> None:
        # Each eval client is a new conversation. The Realtime websocket keeps
        # the previous items unless we reset; LLMRunFrame also only greets on
        # the first context frame of a session.
        if (
            isinstance(self._llm, OpenAIRealtimeLLMService)
            and self._llm._context is not None
        ):
            await self._llm.reset_conversation()
            self._llm._context = None
        if self._greeting_task is not None:
            self._greeting_task.cancel()
            try:
                await self._greeting_task
            except asyncio.CancelledError:
                pass
            self._greeting_task = None
        if not self.pipeline_config.initial_message:
            return
        if self._video_in_enabled():
            self._greeting_task = asyncio.create_task(self._greet_after_perception())
            return
        await self._queue_greeting([])

    async def _on_client_disconnected(self, transport, client) -> None:
        if self._greeting_task is not None:
            self._greeting_task.cancel()
            self._greeting_task = None
        if self._worker is not None:
            await self._worker.cancel()

    async def _resolve_transport(
        self, runner_args: RunnerArguments | None
    ) -> BaseTransport:
        if self._transport is not None:
            return self._transport
        if runner_args is None:
            raise ValueError(
                "runner_args is required when MioPipelineConfig.transport is unset"
            )
        self._transport = await create_transport(
            runner_args, DEFAULT_TRANSPORT_PARAMS
        )
        return self._transport

    async def run_async(
        self, runner_args: RunnerArguments | None = None
    ) -> None:
        transport = await self._resolve_transport(runner_args)

        self._set_state(MioPipelineState.LOADING)
        retrieval_engine = self._create_retrieval_engine()
        embed_tool = EmbedKnowledgeTool(retrieval_engine.embed)
        face_store = self.pipeline_config.face_store or FaceStore()
        face_backend = self.pipeline_config.face_backend or NoOpFaceBackend()

        messages = []
        context = LLMContext(messages)
        perception = PerceptionEngine(face_backend, face_store, context)
        first_frame = FirstFrameGate(skipped=not self._video_in_enabled())
        self._context = context
        self._perception = perception
        self._first_frame = first_frame
        name_tool = NamePersonTool(perception.name_person)
        who_tool = WhoIsFacingTool(perception.who_is_facing)
        context.set_tools([embed_tool, name_tool, who_tool])

        self._loading_service = "llm"
        llm = self._create_llm(
            embed_tool.name,
            extra_instruction=(
                " People facing the camera may be listed in a system message. "
                "Listed names are likely matches: say them without hedging. "
                "You do not have to acknowledge someone who appeared after the "
                "greeting. If the user just said something that needs a reply, "
                "answer that first and do not greet a new person if it would "
                "derail. Only address people currently listed. Do not invent "
                "names. "
                f"Call {name_tool.name} when someone identifies an unrecognized "
                "person and more than one person is facing the camera. "
                f"Call {who_tool.name} if you need to know who is facing the "
                "camera right now."
            ),
        )
        self._llm = llm
        if llm is None:
            self._set_state(MioPipelineState.FAILED)
            return

        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            realtime_service_mode=True,
        )

        stages = [
            transport.input(),
            first_frame,
            perception,
            user_aggregator,
            retrieval_engine,
            llm,
            transport.output(),
            assistant_aggregator,
        ]
        pipeline = Pipeline(stages)

        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(),
            observers=[TerminalDashboard()],
        )
        self._set_state(MioPipelineState.STARTING)

        @self._worker.event_handler("on_pipeline_started")
        async def on_pipeline_started(worker, frame):
            self._set_state(MioPipelineState.READY)

        @self._worker.event_handler("on_pipeline_error")
        async def on_pipeline_error(worker, frame):
            self._set_state(MioPipelineState.FAILED)

        @self._worker.event_handler("on_pipeline_finished")
        async def on_pipeline_finished(worker, frame):
            self._set_state(MioPipelineState.FINISHED)

        transport.add_event_handler("on_client_connected", self._on_client_connected)
        transport.add_event_handler("on_client_disconnected", self._on_client_disconnected)

        runner = WorkerRunner()
        await runner.add_workers(self._worker)
        await runner.run()
