import logging
import re
from typing import override

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams
from pipecat.frames.frames import (
    ErrorFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.text.base_text_filter import BaseTextFilter

from mio_core_services.constants import (
    DEFAULT_SMART_TURN_STOP_SECS,
    DEFAULT_VAD_CONFIDENCE,
    DEFAULT_VAD_MIN_VOLUME,
    DEFAULT_VAD_START_SECS,
    DEFAULT_VAD_STOP_SECS,
)

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
            data.source, OpenAIRealtimeLLMService
        ):
            logger.info("YOU   > %s", data.frame.text)
        elif isinstance(data.frame, LLMTextFrame) and isinstance(
            data.source, OpenAIRealtimeLLMService
        ):
            logger.info(data.frame.text)
        elif isinstance(data.frame, LLMFullResponseEndFrame) and isinstance(
            data.source, OpenAIRealtimeLLMService
        ):
            logger.info("\n")
        elif isinstance(data.frame, ErrorFrame):
            logger.error("\nERROR > %s", data.frame.error)


def create_default_vad_analyzer() -> VADAnalyzer:
    return SileroVADAnalyzer(
        params=VADParams(
            confidence=DEFAULT_VAD_CONFIDENCE,
            start_secs=DEFAULT_VAD_START_SECS,
            stop_secs=DEFAULT_VAD_STOP_SECS,
            min_volume=DEFAULT_VAD_MIN_VOLUME,
        )
    )


def create_default_user_turn_strategies() -> UserTurnStrategies:
    # Prevent speaker → mic feedback from interrupting TTS.
    return UserTurnStrategies(
        stop=[
            TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=LocalSmartTurnAnalyzerV3(
                    params=SmartTurnParams(stop_secs=DEFAULT_SMART_TURN_STOP_SECS),
                )
            )
        ]
    )
