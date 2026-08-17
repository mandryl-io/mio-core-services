"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
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

from mio_core_services.memory import MioVectorStore, RetrievalEngine
from mio_core_services.tools import EmbedKnowledgeTool
from mio_core_services.utils import EmojiTextFilter, TerminalDashboard

from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.text.base_text_filter import BaseTextFilter
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter
from pipecat.workers.runner import WorkerRunner
from pipecat.turns.user_mute import FirstSpeechUserMuteStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_start import VADUserTurnStartStrategy
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy


logger = logging.getLogger(__name__)


@dataclass
class MioPipelineConfig:
    llm_model: str
    system_instruction: str
    transport: BaseTransport
    vector_store: MioVectorStore | None = None


class MioPipeline:
    """Minimal local voice pipeline: Whisper STT → Ollama LLM → Kokoro TTS.

    Pass any Pipecat transport (e.g. SmallWebRTCTransport).
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
        self._worker: PipelineWorker | None = None

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

    async def _on_client_connected(self, transport, client) -> None:
        if self._worker is not None:
            await self._worker.queue_frames([LLMRunFrame()])

    async def _on_client_disconnected(self, transport, client) -> None:
        if self._worker is not None:
            await self._worker.cancel()

    async def run_async(self) -> None:
        stt = self._create_stt()
        if stt is None:
            return

        retrieval_engine = self._create_retrieval_engine()
        embed_tool = (
            EmbedKnowledgeTool(retrieval_engine.embed)
            if retrieval_engine is not None
            else None
        )

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

        context.add_message({
            "role": "developer",
            "content": "Please introduce yourself to the user."
        })

        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(
                        confidence=0.8,
                        start_secs=0.2,
                        stop_secs=0.2,
                        min_volume=0.5,
                    )
                ),
                # Prevent speaker → mic feedback from interrupting TTS.
                user_turn_strategies=UserTurnStrategies(
                    stop=[
                        TurnAnalyzerUserTurnStopStrategy(
                            turn_analyzer=LocalSmartTurnAnalyzerV3(
                                params=SmartTurnParams(stop_secs=1.0),
                            )
                        )
                    ]
                )
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

        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(),
            observers=[TerminalDashboard()],
        )
        self._transport.add_event_handler("on_client_connected", self._on_client_connected)
        self._transport.add_event_handler("on_client_disconnected", self._on_client_disconnected)

        runner = WorkerRunner()
        await runner.add_workers(self._worker)
        await runner.run()
