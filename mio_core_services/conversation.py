import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("PA_ALSA_PLUGHW", "1")

from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    TurnHandlingOptions,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics, openai

from mio_core_services.constants import (
    DEFAULT_CONVERSATION_LLM_MODEL,
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_STT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TTS_VOICE,
)

REQUIRED_ENV_VARS = (
    "OPENAI_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


def require_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=DEFAULT_SYSTEM_PROMPT)


def create_session() -> AgentSession:
    return AgentSession(
        stt=openai.STT(model=DEFAULT_STT_MODEL, language="en"),
        llm=openai.LLM(model=DEFAULT_CONVERSATION_LLM_MODEL),
        tts=openai.TTS(model="tts-1", voice=DEFAULT_TTS_VOICE),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
    )


server = AgentServer()


@server.rtc_session(agent_name="mio-conversation")
async def mio_conversation(ctx: agents.JobContext):
    session = create_session()
    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )
    await session.generate_reply(instructions=DEFAULT_INITIAL_MESSAGE)


def main() -> None:
    load_dotenv()
    os.environ.setdefault("PA_ALSA_PLUGHW", "1")
    require_env()
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()
