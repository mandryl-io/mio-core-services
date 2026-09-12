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
from livekit.plugins import (
    ai_coustics,
    openai,
)

from mio_core_services.constants import (
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_LLM_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.session_usage import (
    attach_session_usage_logging,
    dump_session_usage,
)


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=DEFAULT_SYSTEM_PROMPT)

server = AgentServer()


async def on_session_end(ctx: agents.JobContext) -> None:
    dump_session_usage(ctx, kind="pipeline", reason="session_end")


@server.rtc_session(agent_name="my-agent", on_session_end=on_session_end)
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        stt=openai.STT(model=DEFAULT_STT_MODEL, language="en"),
        llm=openai.LLM(model=DEFAULT_LLM_MODEL),
        tts=openai.TTS(
            model="tts-1",
            voice=DEFAULT_TTS_VOICE,
            response_format="pcm",
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
    )
    attach_session_usage_logging(ctx, session, kind="pipeline")

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(model=ai_coustics.EnhancerModel.QUAIL_VF_S),
            ),
        ),
    )

    await session.generate_reply(
        instructions=DEFAULT_INITIAL_MESSAGE
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
