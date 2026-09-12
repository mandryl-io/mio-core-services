import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("PA_ALSA_PLUGHW", "1")

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import (
    openai,
    ai_coustics,
)

from mio_core_services.constants import DEFAULT_INITIAL_MESSAGE, DEFAULT_SYSTEM_PROMPT

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=DEFAULT_SYSTEM_PROMPT)

server = AgentServer()

@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="alloy",
            turn_detection=None,
        ),
        aec_warmup_duration=0,
    )

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