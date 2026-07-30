"""Simple local voice pipeline powered by Pipecat."""

from __future__ import annotations

from typing import override

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    ErrorFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
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
from pipecat.workers.runner import WorkerRunner


class TerminalDashboard(BaseObserver):
    """Print the useful voice-agent activity without logging every frame."""

    @override
    async def on_pipeline_started(self) -> None:
        print("\n🎙  Voice pipeline ready — listening (Ctrl+C to stop)\n")

    @override
    async def on_push_frame(self, data: FramePushed) -> None:
        if isinstance(data.frame, TranscriptionFrame) and isinstance(
            data.source, WhisperSTTService
        ):
            print(f"YOU  › {data.frame.text}")
        elif isinstance(data.frame, LLMTextFrame) and isinstance(
            data.source, OLLamaLLMService
        ):
            print(data.frame.text, end="", flush=True)
        elif isinstance(data.frame, LLMFullResponseEndFrame) and isinstance(
            data.source, OLLamaLLMService
        ):
            print("\n")
        elif isinstance(data.frame, ErrorFrame):
            print(f"\nERROR › {data.frame.error}")


class MioPipeline:
    """Minimal local voice pipeline: Whisper STT → Ollama LLM → Kokoro TTS.

    Pass any Pipecat transport (e.g. LocalAudioTransport for mic/speakers).
    Requires a running Ollama server with the chosen model pulled.
    """

    def __init__(
        self,
        transport: BaseTransport,
        *,
        llm_model: str = "qwen2.5-coder:7b",
        system_instruction: str = (
            "You are a helpful voice assistant. "
            "Keep replies brief and conversational."
        ),
    ) -> None:
        self._transport: BaseTransport = transport
        self._llm_model: str = llm_model
        self._system_instruction: str = system_instruction

    async def run_async(self) -> None:
        stt = WhisperSTTService(
            settings=WhisperSTTService.Settings(model="base"),
        )
        llm = OLLamaLLMService(
            settings=OLLamaLLMService.Settings(
                model=self._llm_model,
                system_instruction=self._system_instruction,
            ),
        )
        tts = KokoroTTSService(
            settings=KokoroTTSService.Settings(voice="af_heart"),
        )

        context = LLMContext()
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                # Prevent speaker → mic feedback from interrupting TTS.
                user_mute_strategies=[AlwaysUserMuteStrategy()],
            ),
        )

        pipeline = Pipeline(
            [
                self._transport.input(),
                stt,
                user_aggregator,
                llm,
                tts,
                self._transport.output(),
                assistant_aggregator,
            ]
        )

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(),
            observers=[TerminalDashboard()],
        )
        runner = WorkerRunner()
        await runner.add_workers(worker)
        await runner.run()
