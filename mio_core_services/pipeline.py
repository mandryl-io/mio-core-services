"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_mute import AlwaysUserMuteStrategy
from pipecat.turns.user_start import (
    TranscriptionUserTurnStartStrategy,
    VADUserTurnStartStrategy,
    WakePhraseUserTurnStartStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.workers.runner import WorkerRunner

from mio_core_services.constants import (
    DEFAULT_LLM_MODEL,
    DEFAULT_MEDICATION_DB_PATH,
    DEFAULT_STT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TRANSPORT_PARAMS,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    DEFAULT_WAKE_PHRASES,
    DEFAULT_WAKE_TIMEOUT_SECS,
)
from mio_core_services.memory import MioVectorStore, RetrievalEngine
from mio_core_services.perception import FaceStore, PerceptionEngine
from mio_core_services.perception.backend import FaceBackend, NoOpFaceBackend
from mio_core_services.reminders import Clock, MedicationReminders, SystemClock
from mio_core_services.tools import (
    EmbedKnowledgeTool,
    NamePersonTool,
    SetMedicationReminderTool,
    WhoIsFacingTool,
)
from mio_core_services.utils import EmojiTextFilter, TerminalDashboard

logger = logging.getLogger(__name__)


class _HalfDuplexMicGate(FrameProcessor):
    """Drop mic audio while Mio is speaking so playback cannot become a turn."""

    def __init__(self) -> None:
        super().__init__()
        self._bot_speaking = False

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        if self._bot_speaking and isinstance(frame, InputAudioRawFrame):
            return
        await self.push_frame(frame, direction)


@dataclass
class MioPipelineConfig:
    vector_store: MioVectorStore
    llm_model: str = DEFAULT_LLM_MODEL
    system_instruction: str = DEFAULT_SYSTEM_PROMPT
    transport: BaseTransport | None = None
    clock: Clock | None = None
    reminder_db_path: str = DEFAULT_MEDICATION_DB_PATH
    initial_message: str | None = None
    face_store: FaceStore | None = None
    face_backend: FaceBackend | None = None


class MioPipelineState(StrEnum):
    IDLE = "idle"
    LOADING = "loading"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    FINISHED = "finished"


class MioPipeline:
    """Voice pipeline: OpenAI STT → OpenAI LLM → OpenAI TTS.

    Requires a ``MioPipelineConfig`` with a ``vector_store``. Other config
    fields default (WebRTC transport, gpt-4.1, system prompt). Requires
    ``OPENAI_API_KEY``.

    Spoken turns start only after the wake phrase "Hey Mio", then stay open
    for a short inactivity timeout. The microphone is muted while Mio speaks.
    """

    def __init__(self, pipeline_config: MioPipelineConfig) -> None:
        self.pipeline_config = pipeline_config
        self._transport: BaseTransport | None = self.pipeline_config.transport
        self._llm_model: str = self.pipeline_config.llm_model
        self._system_instruction: str = self.pipeline_config.system_instruction
        self._worker: PipelineWorker | None = None
        self._llm: OpenAILLMService | None = None
        self._state = MioPipelineState.IDLE
        self._loading_service: Literal["stt", "llm", "tts"] | None = None
        self._ready_event = asyncio.Event()

    @property
    def state(self) -> MioPipelineState:
        return self._state

    @property
    def loading_service(self) -> Literal["stt", "llm", "tts"] | None:
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

    def _create_stt(self) -> OpenAISTTService | None:
        try:
            return OpenAISTTService(
                api_key=self._openai_api_key(),
                settings=OpenAISTTService.Settings(model=DEFAULT_STT_MODEL),
            )
        except Exception:
            logger.exception("MioPipeline: failed to start OpenAI STT service")
            return None

    def _create_llm(
        self,
        embed_tool_name: str | None = None,
        reminder_tool_name: str | None = None,
        extra_instruction: str = "",
    ) -> OpenAILLMService | None:
        try:
            api_key = self._openai_api_key()
            system_instruction = self._system_instruction
            if embed_tool_name is not None:
                system_instruction += (
                    " Retrieved knowledge may be attached to each turn; use it when "
                    "it is relevant and ignore it otherwise. "
                    f"Call {embed_tool_name} when the user asks you to remember a fact."
                )
            if reminder_tool_name is not None:
                system_instruction += (
                    f" When they want a medication reminder, call {reminder_tool_name} "
                    "with what they already said. Omit unknowns. Do not invent a "
                    "medication, time, or frequency. After the tool replies, say that "
                    "sentence and return to companionship."
                )
            if extra_instruction:
                system_instruction += extra_instruction
            return OpenAILLMService(
                api_key=api_key,
                settings=OpenAILLMService.Settings(
                    model=self._llm_model,
                    system_instruction=system_instruction,
                ),
            )
        except Exception:
            logger.exception("MioPipeline: failed to start OpenAI LLM service")
            return None

    def _create_tts(self) -> OpenAITTSService | None:
        try:
            return OpenAITTSService(
                api_key=self._openai_api_key(),
                settings=OpenAITTSService.Settings(
                    model=DEFAULT_TTS_MODEL,
                    voice=DEFAULT_TTS_VOICE,
                ),
                text_filters=[MarkdownTextFilter(), EmojiTextFilter()],
            )
        except Exception:
            logger.exception("MioPipeline: failed to start OpenAI TTS service")
            return None

    def _user_aggregator_params(self) -> LLMUserAggregatorParams:
        return LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                start=[
                    WakePhraseUserTurnStartStrategy(
                        phrases=list(DEFAULT_WAKE_PHRASES),
                        timeout=DEFAULT_WAKE_TIMEOUT_SECS,
                    ),
                    VADUserTurnStartStrategy(enable_interruptions=False),
                    TranscriptionUserTurnStartStrategy(enable_interruptions=False),
                ],
            ),
            user_mute_strategies=[AlwaysUserMuteStrategy()],
        )

    def _create_retrieval_engine(self) -> RetrievalEngine:
        return RetrievalEngine(self.pipeline_config.vector_store)

    async def _on_client_connected(self, transport, client) -> None:
        print("\nClient connected\n", flush=True)

    async def _on_client_disconnected(self, transport, client) -> None:
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
        self._transport = await create_transport(runner_args, DEFAULT_TRANSPORT_PARAMS)
        return self._transport

    async def run_async(self, runner_args: RunnerArguments | None = None) -> None:
        transport = await self._resolve_transport(runner_args)

        self._set_state(MioPipelineState.LOADING)
        retrieval_engine = self._create_retrieval_engine()
        embed_tool = EmbedKnowledgeTool(retrieval_engine.embed)
        reminders = MedicationReminders(
            self.pipeline_config.reminder_db_path,
            self.pipeline_config.clock or SystemClock(),
        )
        set_tool = SetMedicationReminderTool(reminders.set)
        face_store = self.pipeline_config.face_store or FaceStore()
        face_backend = self.pipeline_config.face_backend or NoOpFaceBackend()

        context = LLMContext()
        perception = PerceptionEngine(face_backend, face_store, context)
        name_tool = NamePersonTool(perception.name_person)
        who_tool = WhoIsFacingTool(perception.who_is_facing)
        context.set_tools([embed_tool, set_tool, name_tool, who_tool])

        self._loading_service = "stt"
        stt = self._create_stt()
        if stt is None:
            self._set_state(MioPipelineState.FAILED)
            return

        self._loading_service = "llm"
        llm = self._create_llm(
            embed_tool.name,
            set_tool.name,
            extra_instruction=(
                " People facing the camera may be listed in a system message. "
                "You do not have to acknowledge them. If the user just said "
                "something that needs a reply, answer that first. Only address "
                "people currently listed. Do not invent names. "
                f"Call {name_tool.name} when someone tells you who an "
                f"unrecognized person is. Call {who_tool.name} if you need to "
                "know who is facing the camera right now."
            ),
        )
        self._llm = llm
        if llm is None:
            self._set_state(MioPipelineState.FAILED)
            return

        self._loading_service = "tts"
        tts = self._create_tts()
        if tts is None:
            self._set_state(MioPipelineState.FAILED)
            return

        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=self._user_aggregator_params(),
        )

        stages = [
            transport.input(),
            _HalfDuplexMicGate(),
            perception,
            stt,
            user_aggregator,
            retrieval_engine,
            reminders,
            llm,
            tts,
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
        transport.add_event_handler(
            "on_client_disconnected", self._on_client_disconnected
        )

        runner = WorkerRunner()
        await runner.add_workers(self._worker)
        await runner.run()
