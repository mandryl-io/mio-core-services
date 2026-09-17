import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    TurnHandlingOptions,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics, anthropic, deepgram

from mio_core_services.constants import (
    DEFAULT_CONVERSATION_LLM_MODEL,
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_MODEL,
)

# NOTE(@dillondesilva): Move this validation to a shared module when another
# service needs the same startup safety check.
REQUIRED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "DEEPGRAM_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


def system_prompt_path() -> Path:
    return Path(os.environ.get("MIO_SYSTEM_PROMPT_PATH", "prompts/default.md"))


def load_system_prompt(path: Path) -> str:
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"System prompt is empty: {path}")
    return prompt


def require_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


class Assistant(Agent):
    def __init__(self, prompt_path: Path) -> None:
        super().__init__(instructions=load_system_prompt(prompt_path))


def create_session() -> AgentSession:
    return AgentSession(
        stt=deepgram.STT(model=DEFAULT_STT_MODEL, language="en"),
        llm=anthropic.LLM(model=DEFAULT_CONVERSATION_LLM_MODEL),
        tts=deepgram.TTS(model=DEFAULT_TTS_MODEL),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
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
    await session.say(DEFAULT_INITIAL_MESSAGE)
