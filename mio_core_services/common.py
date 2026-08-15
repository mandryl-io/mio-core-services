import logging
from typing import override

from pipecat.frames.frames import (
    ErrorFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.whisper.stt import WhisperSTTService

logger = logging.getLogger(__name__)

MIO_LOCAL_VEC_MEMORY_STORE = "mio-local-vec-memory-store"


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
            logger.info("YOU   > %s", data.frame.text)
        elif isinstance(data.frame, LLMTextFrame) and isinstance(
            data.source, OLLamaLLMService
        ):
            logger.info(data.frame.text)
        elif isinstance(data.frame, LLMFullResponseEndFrame) and isinstance(
            data.source, OLLamaLLMService
        ):
            logger.info("\n")
        elif isinstance(data.frame, ErrorFrame):
            logger.error("\nERROR > %s", data.frame.error)
