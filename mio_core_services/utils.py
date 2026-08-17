import logging
import re
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
from pipecat.utils.text.base_text_filter import BaseTextFilter

logger = logging.getLogger(__name__)


class EmojiTextFilter(BaseTextFilter):
    """Strip Unicode emoji and :shortcode: tokens so TTS does not speak them."""

    _SHORTCODE = re.compile(r":[a-zA-Z0-9_+-]+:")
    _EMOJI = re.compile(
        "["
        "\U0001F1E6-\U0001F1FF"  # flags
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F700-\U0001FAFF"  # alchemical through symbols extended-A
        "\U00002600-\U000027BF"  # misc symbols & dingbats
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0000200D"  # zero-width joiner
        "\U000020E3"  # combining enclosing keycap
        "]+"
    )
    _MULTI_SPACE = re.compile(r" {2,}")

    async def filter(self, text: str) -> str:
        text = self._SHORTCODE.sub("", text)
        text = self._EMOJI.sub("", text)
        return self._MULTI_SPACE.sub(" ", text)


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
