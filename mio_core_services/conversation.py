import asyncio
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
    AgentStateChangedEvent,
    RunContext,
    TurnHandlingOptions,
    function_tool,
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
from mio_core_services.first_use import (
    FirstUseGuide,
    PATIENT_PROFILE_QUERY,
    SetupStore,
    agent_instructions,
    format_setup_context,
    is_first_use,
    merge_startup_context,
    opening_turn_instructions,
    patient_name_for_device,
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

# Keep the mic off until speaker echo from TTS has died away.
MIC_UNMUTE_HOLD_S = 0.5
# Wait long enough after a pause that slower speakers keep their turn.
USER_TURN_MIN_ENDPOINTING_S = 1.5
USER_TURN_MAX_ENDPOINTING_S = 6.0

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
        setup_store: SetupStore | None = None,
        first_use: bool | None = None,
    ) -> None:
        self._memory = memory if memory is not None else Mem0TurnMemory.from_env()
        store = setup_store if setup_store is not None else SetupStore.from_env()
        self._guide = FirstUseGuide(store, self._memory)
        self._first_use = (
            is_first_use(state=self._guide.state)
            if first_use is None
            else first_use
        )
        super().__init__(
            instructions=agent_instructions(
                prompt_path,
                first_use=self._first_use,
                state=self._guide.state,
                load_prompt=load_system_prompt,
            ),
            turn_handling=TurnHandlingOptions(
                interruption={"enabled": False},
            ),
        )

    @property
    def first_use(self) -> bool:
        return self._first_use

    @property
    def setup_state(self):
        return self._guide.state

    async def on_enter(self) -> None:
        if self._first_use:
            return
        recalled = await self._memory.recall_context(PATIENT_PROFILE_QUERY)
        context = merge_startup_context(
            format_setup_context(self._guide.state),
            recalled,
        )
        if not context:
            return
        chat_ctx = self.chat_ctx.copy()
        chat_ctx.add_message(role="system", content=context)
        await self.update_chat_ctx(chat_ctx)

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        text = getattr(new_message, "text_content", None) or ""
        if await inject_mem0_turn(self._memory, turn_ctx, text):
            await self.update_chat_ctx(turn_ctx)
        await super().on_user_turn_completed(turn_ctx, new_message)


class FirstUseAssistant(Assistant):
    @function_tool()
    async def save_patient_name(self, context: RunContext, name: str) -> str:
        """Save the confirmed name of the person this Mio device is for.

        Args:
            name: The name after you have clarified it with them.
        """
        return await self._guide.save_patient_name(name)

    @function_tool()
    async def save_carer_name(self, context: RunContext, name: str) -> str:
        """Save the confirmed name of a carer present in the room.

        Args:
            name: The carer's name, not the patient's name.
        """
        return await self._guide.save_carer_name(name)

    @function_tool()
    async def save_patient_notes(
        self,
        context: RunContext,
        dementia: str | None = None,
        lifestyle: str | None = None,
        interests_and_hobbies: str | None = None,
        daily_exercise: str | None = None,
        mobility: str | None = None,
        mio_preferences: str | None = None,
    ) -> str:
        """Save what you have learned in the Learn Patient questions.

        Args:
            dementia: Whether they have dementia, in their own words.
            lifestyle: A little about how they spend their days.
            interests_and_hobbies: Interests and hobbies.
            daily_exercise: How often they exercise in a day.
            mobility: Walker, other mobility support, or mobility issues.
            mio_preferences: Anything specific they would like Mio to do.
        """
        return await self._guide.save_patient_notes(
            dementia=dementia,
            lifestyle=lifestyle,
            interests_and_hobbies=interests_and_hobbies,
            daily_exercise=daily_exercise,
            mobility=mobility,
            mio_preferences=mio_preferences,
        )

    @function_tool()
    async def complete_first_use_setup(self, context: RunContext) -> str:
        """Call this after Learn Patient is finished so later starts skip setup."""
        return await self._guide.complete_setup()


def create_assistant(
    prompt_path: Path,
    memory: Mem0TurnMemory | None = None,
    setup_store: SetupStore | None = None,
) -> Assistant:
    store = setup_store if setup_store is not None else SetupStore.from_env()
    memory = memory if memory is not None else Mem0TurnMemory.from_env()
    state = store.load()
    agent_cls = FirstUseAssistant if is_first_use(state=state) else Assistant
    return agent_cls(
        prompt_path,
        memory=memory,
        setup_store=store,
        first_use=is_first_use(state=state),
    )


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
            endpointing={
                "mode": "fixed",
                "min_delay": USER_TURN_MIN_ENDPOINTING_S,
                "max_delay": USER_TURN_MAX_ENDPOINTING_S,
            },
            interruption={"enabled": False},
        ),
    )


def start_opening_turn(
    session: AgentSession,
    instructions: str | None = None,
):
    return session.generate_reply(
        instructions=instructions or INITIAL_GREETING_INSTRUCTIONS,
        allow_interruptions=False,
    )


def bind_mic_mute_while_speaking(session: AgentSession) -> None:
    unmute_task: asyncio.Task[None] | None = None

    def cancel_pending_unmute() -> None:
        nonlocal unmute_task
        if unmute_task is not None and not unmute_task.done():
            unmute_task.cancel()
        unmute_task = None

    async def unmute_after_hold() -> None:
        await asyncio.sleep(MIC_UNMUTE_HOLD_S)
        session.input.set_audio_enabled(True)

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        nonlocal unmute_task
        if ev.new_state == "speaking":
            cancel_pending_unmute()
            session.input.set_audio_enabled(False)
            return
        if ev.old_state != "speaking":
            return
        cancel_pending_unmute()
        unmute_task = asyncio.create_task(unmute_after_hold())


server = AgentServer()


@server.rtc_session(agent_name="mio-conversation")
async def mio_conversation(ctx: agents.JobContext):
    require_env()
    memory = Mem0TurnMemory.from_env()
    agent = create_assistant(system_prompt_path(), memory=memory)
    session = create_session()
    bind_mic_mute_while_speaking(session)
    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )
    await start_opening_turn(
        session,
        opening_turn_instructions(
            first_use=agent.first_use,
            patient_name=patient_name_for_device(agent.setup_state),
            setup_completed=agent.setup_state.completed,
        ),
    )
