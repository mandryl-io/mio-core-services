import logging
import re
import resource
import sys
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
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from loguru import logger as loguru_logger
from pipecat.utils.text.base_text_filter import BaseTextFilter

from mio_core_services.constants import (
    DEFAULT_SMART_TURN_STOP_SECS,
    DEFAULT_VAD_CONFIDENCE,
    DEFAULT_VAD_MIN_VOLUME,
    DEFAULT_VAD_START_SECS,
    DEFAULT_VAD_STOP_SECS,
)

logger = logging.getLogger(__name__)


def _rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024
    return rss


def _format_bytes(n: int) -> str:
    for unit, denom in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if n >= denom:
            return f"{n / denom:.1f} {unit}"
    return f"{n} B"


class ServiceMemoryTracker:
    """Record RSS added by each service as it starts, then log a summary."""

    def __init__(self) -> None:
        self._last = _rss_bytes()
        self._usage: list[tuple[str, int]] = []

    def mark(self, name: str) -> None:
        now = _rss_bytes()
        self._usage.append((name, max(0, now - self._last)))
        self._last = now

    def log(self) -> None:
        parts = "  ".join(f"{name}={_format_bytes(n)}" for name, n in self._usage)
        combined = sum(n for _, n in self._usage)
        message = (
            f"service memory  {parts}  combined={_format_bytes(combined)}  "
            f"process={_format_bytes(_rss_bytes())}"
        )
        loguru_logger.info("MioPipeline: {}", message)
        print(f"\n{message}\n")


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
