import os
from collections.abc import MutableMapping
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    TurnHandlingOptions,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics, baseten, deepgram, openai, silero

from mio_core_services.constants import (
    DEFAULT_CONVERSATION_LLM_MODEL,
    DEFAULT_CONVERSATION_LLM_REASONING_EFFORT,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_INSTRUCTIONS,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    INITIAL_GREETING_INSTRUCTIONS,
)
from mio_core_services.memory.mem0 import Mem0TurnMemory, inject_mem0_turn

# NOTE(@dillondesilva): Move this validation to a shared module when another
# service needs the same startup safety check.
REQUIRED_ENV_VARS = (
    "BASETEN_API_KEY",
    "DEEPGRAM_API_KEY",
    "OPENAI_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)

# systemd does not load /etc/environment. If the key is set at OS/root
# level, pick it up from these files when the process env is empty.
_OS_LEVEL_ENV_FILES = (
    Path("/etc/environment"),
    Path("/etc/default/mio"),
)


def system_prompt_path() -> Path:
    return Path(os.environ.get("MIO_SYSTEM_PROMPT_PATH", "prompts/default.md"))


def _env_file_value(path: Path, name: str) -> str | None:
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ")
        key, separator, value = line.partition("=")
        if separator and key.strip() == name:
            return value.strip().strip("'").strip('"') or None
    return None


def apply_os_level_baseten_api_key(
    environ: MutableMapping[str, str] | None = None,
    env_files: tuple[Path, ...] | None = None,
) -> None:
    env = os.environ if environ is None else environ
    if env.get("BASETEN_API_KEY"):
        return
    files = _OS_LEVEL_ENV_FILES if env_files is None else env_files
    for path in files:
        value = _env_file_value(path, "BASETEN_API_KEY")
        if value:
            env["BASETEN_API_KEY"] = value
            return


def baseten_api_key() -> str | None:
    apply_os_level_baseten_api_key()
    return os.environ.get("BASETEN_API_KEY")


def load_system_prompt(path: Path) -> str:
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"System prompt is empty: {path}")
    return prompt


def require_env() -> None:
    apply_os_level_baseten_api_key()
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


class Assistant(Agent):
    def __init__(
        self,
        prompt_path: Path,
        memory: Mem0TurnMemory | None = None,
    ) -> None:
        super().__init__(
            instructions=load_system_prompt(prompt_path),
            turn_handling=TurnHandlingOptions(
                interruption={"enabled": True, "mode": "adaptive"},
            ),
        )
        self._memory = memory if memory is not None else Mem0TurnMemory.from_env()

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        text = getattr(new_message, "text_content", None) or ""
        if await inject_mem0_turn(self._memory, turn_ctx, text):
            await self.update_chat_ctx(turn_ctx)
        await super().on_user_turn_completed(turn_ctx, new_message)


def create_session() -> AgentSession:
    return AgentSession(
        stt=deepgram.STT(model=DEFAULT_STT_MODEL, language="en"),
        llm=baseten.LLM(
            model=DEFAULT_CONVERSATION_LLM_MODEL,
            api_key=baseten_api_key(),
            reasoning_effort=DEFAULT_CONVERSATION_LLM_REASONING_EFFORT,
        ),
        tts=openai.TTS(
            model=DEFAULT_TTS_MODEL,
            voice=DEFAULT_TTS_VOICE,
            instructions=DEFAULT_TTS_INSTRUCTIONS,
        ),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={
                "enabled": True,
                "mode": "adaptive",
                "min_duration": 0.5,
                "min_words": 0,
            },
        ),
        )


def start_opening_turn(session: AgentSession):
    return session.generate_reply(
        instructions=INITIAL_GREETING_INSTRUCTIONS,
        allow_interruptions=True,
    )


server = AgentServer()


@server.rtc_session(agent_name="mio-conversation")
async def mio_conversation(ctx: agents.JobContext):
    require_env()
    session = create_session()
    await session.start(
        room=ctx.room,
        agent=Assistant(system_prompt_path()),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )
    await start_opening_turn(session)
