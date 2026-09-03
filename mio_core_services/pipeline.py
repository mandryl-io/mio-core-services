"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.base_transport import BaseTransport
from mio_core_services.constants import (
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_LLM_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TRANSPORT_PARAMS,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.memory import MioVectorStore, RetrievalEngine
from mio_core_services.tools import EmbedKnowledgeTool
from mio_core_services.utils import (
    EmojiTextFilter,
    TerminalDashboard,
    create_default_user_turn_strategies,
    create_default_vad_analyzer,
)

from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.workers.runner import WorkerRunner
from pipecat.turns.user_turn_strategies import UserTurnStrategies


logger = logging.getLogger(__name__)


@dataclass
class MioPipelineConfig:
    vector_store: MioVectorStore
    llm_model: str = DEFAULT_LLM_MODEL
    system_instruction: str = DEFAULT_SYSTEM_PROMPT
    transport: BaseTransport | None = None
    # Spoken on connect via TTS so the greeting does not wait on the LLM.
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
    """Voice pipeline: OpenAI STT → OpenAI LLM → OpenAI TTS.

    Requires a ``MioPipelineConfig`` with a ``vector_store``. Other config
    fields default (WebRTC transport, gpt-5.4-mini, system prompt). Requires
    ``OPENAI_API_KEY`` in the environment.
    """

    def __init__(self, pipeline_config: MioPipelineConfig) -> None:
        self.pipeline_config = pipeline_config
        self._transport: BaseTransport | None = self.pipeline_config.transport
        self._llm_model: str = self.pipeline_config.llm_model
        self._system_instruction: str = self.pipeline_config.system_instruction
        self._worker: PipelineWorker | None = None
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

    def _create_llm(self, embed_tool_name: str | None = None) -> OpenAILLMService | None:
        try:
            api_key = self._openai_api_key()
            system_instruction = self._system_instruction
            if embed_tool_name is not None:
                system_instruction += (
                    " Retrieved knowledge may be attached to each turn; use it when "
                    "it is relevant and ignore it otherwise. "
                    f"Call {embed_tool_name} when the user asks you to remember a fact."
                )
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
            md_filter = MarkdownTextFilter()
            emoji_filter = EmojiTextFilter()
            return OpenAITTSService(
                api_key=self._openai_api_key(),
                settings=OpenAITTSService.Settings(
                    model=DEFAULT_TTS_MODEL,
                    voice=DEFAULT_TTS_VOICE,
                ),
                text_filters=[md_filter, emoji_filter],
            )
        except Exception:
            logger.exception("MioPipeline: failed to start OpenAI TTS service")
            return None

    def _create_retrieval_engine(self) -> RetrievalEngine:
        return RetrievalEngine(self.pipeline_config.vector_store)

    async def _on_client_connected(self, transport, client) -> None:
        if self._worker is not None and self.pipeline_config.initial_message:
            await self._worker.queue_frames([
                TTSSpeakFrame(text=self.pipeline_config.initial_message)
            ])

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
        self._loading_service = "stt"
        stt = self._create_stt()
        if stt is None:
            self._set_state(MioPipelineState.FAILED)
            return

        retrieval_engine = self._create_retrieval_engine()
        embed_tool = EmbedKnowledgeTool(retrieval_engine.embed)

        self._loading_service = "llm"
        llm = self._create_llm(embed_tool.name)
        if llm is None:
            self._set_state(MioPipelineState.FAILED)
            return

        self._loading_service = "tts"
        tts = self._create_tts()
        if tts is None:
            self._set_state(MioPipelineState.FAILED)
            return

        context = LLMContext(tools=[embed_tool])
        if embed_tool.handler is not None:
            llm.register_function(embed_tool.name, embed_tool.handler)

        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=self.pipeline_config.vad_analyzer,
                user_turn_strategies=self.pipeline_config.user_turn_strategies,
            ),
        )

        stages = [
            transport.input(),
            stt,
            user_aggregator,
            retrieval_engine,
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
        transport.add_event_handler("on_client_disconnected", self._on_client_disconnected)

        runner = WorkerRunner()
        await runner.add_workers(self._worker)
        await runner.run()
