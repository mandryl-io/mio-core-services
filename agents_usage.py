import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("PA_ALSA_PLUGHW", "1")

from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, room_io
from livekit.plugins import (
    ai_coustics,
    openai,
)
from openai.types.realtime import AudioTranscription

from mio_core_services.constants import DEFAULT_INITIAL_MESSAGE, DEFAULT_SYSTEM_PROMPT
from mio_core_services.session_usage import (
    attach_session_usage_logging,
    dump_session_usage,
)


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=DEFAULT_SYSTEM_PROMPT)

server = AgentServer()


async def on_session_end(ctx: agents.JobContext) -> None:
    dump_session_usage(ctx, kind="realtime", reason="session_end")


@server.rtc_session(agent_name="my-agent", on_session_end=on_session_end)
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="alloy",
            turn_detection=None,
            input_audio_transcription=AudioTranscription(
                model="gpt-4o-mini-transcribe",
                language="en",
            ),
        ),
        aec_warmup_duration=0,
    )
    attach_session_usage_logging(ctx, session, kind="realtime")

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
