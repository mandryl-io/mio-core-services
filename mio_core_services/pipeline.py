"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    AudioOutput,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    SessionProperties,
)
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.base_transport import BaseTransport
from mio_core_services.constants import (
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_LLM_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TRANSCRIPTION_MODEL,
    DEFAULT_TRANSPORT_PARAMS,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.memory import MioVectorStore, RetrievalEngine
from mio_core_services.tools import EmbedKnowledgeTool
from mio_core_services.utils import (
    TerminalDashboard,
    create_default_user_turn_strategies,
    create_default_vad_analyzer,
)

from pipecat.workers.runner import WorkerRunner
from pipecat.turns.user_turn_strategies import UserTurnStrategies


logger = logging.getLogger(__name__)

# Pipecat's InputAudioTranscription.__init__ only accepts model/language/prompt.
# gpt-live-transcribe session echoes also include `languages`, which crashes
# parse_server_event on session.updated.
_original_input_audio_transcription_init = InputAudioTranscription.__init__


def _init_input_audio_transcription(self, *args, **kwargs) -> None:
    kwargs.pop("languages", None)
    _original_input_audio_transcription_init(self, *args, **kwargs)


InputAudioTranscription.__init__ = _init_input_audio_transcription


@dataclass
class MioPipelineConfig:
    vector_store: MioVectorStore
    llm_model: str = DEFAULT_LLM_MODEL
    system_instruction: str = DEFAULT_SYSTEM_PROMPT
    transport: BaseTransport | None = None
    # Spoken on connect by kicking the realtime model so the greeting
    # is the first assistant turn.
    initial_message: str | None = DEFAULT_INITIAL_MESSAGE
    vad_analyzer: VADAnalyzer = field(default_factory=create_default_vad_analyzer)
    user_turn_strategies: UserTurnStrategies = field(
        default_factory=create_default_user_turn_strategies
    )


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
        self._state = MioPipelineState.IDLE
        self._loading_service: Literal["llm"] | None = None
        self._ready_event = asyncio.Event()

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
        self, embed_tool_name: str | None = None
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
            return OpenAIRealtimeLLMService(
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
                                turn_detection=False,
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

    async def _on_client_connected(self, transport, client) -> None:
        if self._worker is not None and self.pipeline_config.initial_message:
            await self._worker.queue_frames([LLMRunFrame()])

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

        self._loading_service = "llm"
        llm = self._create_llm(embed_tool.name)
        if llm is None:
            self._set_state(MioPipelineState.FAILED)
            return

        messages = []
        if self.pipeline_config.initial_message:
            messages.append(
                {
                    "role": "developer",
                    "content": (
                        "Greet the user by saying exactly this, then wait for "
                        "them to speak: "
                        f"{self.pipeline_config.initial_message}"
                    ),
                }
            )
        context = LLMContext(messages, tools=[embed_tool])

        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=self.pipeline_config.vad_analyzer,
                user_turn_strategies=self.pipeline_config.user_turn_strategies,
            ),
            realtime_service_mode=True,
        )

        stages = [
            transport.input(),
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
