"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_mute import AlwaysUserMuteStrategy
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.workers.runner import WorkerRunner

from mio_core_services.common import TerminalDashboard
from mio_core_services.retrieval_engine import RetrievalEngine
from mio_core_services.utils import EmojiTextFilter
from mio_core_services.vector_store.base import MioVectorStore

logger = logging.getLogger(__name__)


@dataclass
class MioPipelineConfig:
    llm_model: str
    system_instruction: str
    transport: BaseTransport
    vector_store: MioVectorStore | None = None


class MioPipeline:
    """Minimal local voice pipeline: Whisper STT → Ollama LLM → Kokoro TTS.

    Pass any Pipecat transport (e.g. LocalAudioTransport for mic/speakers).
    Requires a running Ollama server with the chosen model pulled.
    """

    def __init__(
        self,
        pipeline_config: MioPipelineConfig,
    ) -> None:
        self.pipeline_config = pipeline_config
        self._transport: BaseTransport = pipeline_config.transport
        self._llm_model: str = pipeline_config.llm_model
        self._system_instruction: str = pipeline_config.system_instruction

    def _create_stt(self) -> WhisperSTTService | None:
        try:
            return WhisperSTTService(
                settings=WhisperSTTService.Settings(model="base"),
            )
        except Exception:
            logger.exception("MioPipeline: failed to start Whisper STT service")
            return None

    def _create_llm(self, embed_tool_name: str | None = None) -> OLLamaLLMService | None:
        try:
            system_instruction = self._system_instruction
            if embed_tool_name is not None:
                system_instruction += (
                    " Retrieved knowledge may be attached to each turn; use it when "
                    "it is relevant and ignore it otherwise. "
                    f"Call {embed_tool_name} when the user asks you to remember a fact."
                )
            return OLLamaLLMService(
                settings=OLLamaLLMService.Settings(
                    model=self._llm_model,
                    system_instruction=system_instruction,
                ),
            )
        except Exception:
            logger.exception("MioPipeline: failed to start Ollama LLM service")
            return None

    def _create_tts(self) -> KokoroTTSService | None:
        try:
            md_filter = MarkdownTextFilter()
            emoji_filter = EmojiTextFilter()
            return KokoroTTSService(
                settings=KokoroTTSService.Settings(voice="af_heart"),
                text_filters=[md_filter, emoji_filter],
            )
        except Exception:
            logger.exception("MioPipeline: failed to start Kokoro TTS service")
            return None

    def _create_retrieval_engine(self) -> RetrievalEngine | None:
        if self.pipeline_config.vector_store is None:
            return None
        return RetrievalEngine(self.pipeline_config.vector_store)

    async def run_async(self) -> None:
        stt = self._create_stt()
        if stt is None:
            return

        retrieval_engine = self._create_retrieval_engine()
        embed_tool = retrieval_engine.tool if retrieval_engine is not None else None

        llm = self._create_llm(embed_tool.name if embed_tool is not None else None)
        if llm is None:
            return

        tts = self._create_tts()
        if tts is None:
            return

        if embed_tool is not None:
            context = LLMContext(tools=[embed_tool])
            if embed_tool.handler is not None:
                llm.register_function(embed_tool.name, embed_tool.handler)
        else:
            context = LLMContext()

        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                # Prevent speaker → mic feedback from interrupting TTS.
                user_mute_strategies=[AlwaysUserMuteStrategy()],
            ),
        )

        stages = [
            self._transport.input(),
            stt,
            user_aggregator,
        ]
        if retrieval_engine is not None:
            stages.append(retrieval_engine)
        stages.extend(
            [
                llm,
                tts,
                self._transport.output(),
                assistant_aggregator,
            ]
        )
        pipeline = Pipeline(stages)

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(),
            observers=[TerminalDashboard()],
        )

        @self._transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            await worker.cancel()

        runner = WorkerRunner()
        await runner.add_workers(worker)
        await runner.run()
