import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("PA_ALSA_PLUGHW", "1")

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, room_io, inference, TurnHandlingOptions
from livekit.plugins import (
    openai,
    ai_coustics,
)

from mio_core_services.constants import (
    DEFAULT_INITIAL_MESSAGE,
    DEFAULT_LLM_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
)

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=DEFAULT_SYSTEM_PROMPT)

server = AgentServer()

@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        stt=openai.STT(model=DEFAULT_STT_MODEL),
        llm=openai.LLM(model=DEFAULT_LLM_MODEL),
        tts=openai.TTS(
            model=DEFAULT_TTS_MODEL,
            voice=DEFAULT_TTS_VOICE,
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
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