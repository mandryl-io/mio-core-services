from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from mio_core_services.constants import DEFAULT_BOT_NAME, INITIAL_GREETING_INSTRUCTIONS

FIRST_USE_ENV = "MIO_FIRST_USE"
USER_NAME_ENV = "MIO_USER_NAME"
SETUP_STATE_PATH_ENV = "MIO_SETUP_STATE_PATH"
DEFAULT_SETUP_STATE_PATH = "mio-setup-state.json"

TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})

PATIENT_PROFILE_QUERY = (
    "patient name carer name dementia lifestyle interests hobbies "
    "exercise mobility preferences health wellbeing"
)

PROFILE_CONTEXT_PREFIX = (
    "Notes from the Learn Patient setup for the person this device belongs to. "
    "Do not read this aloud as a list. Use it so the conversation can feel "
    "informed, gentle, and continuous."
)

FIRST_USE_OPENING_INSTRUCTIONS = (
    f"This is {DEFAULT_BOT_NAME}'s first time with this person. Introduce "
    f"yourself as {DEFAULT_BOT_NAME} in one or two short, warm, gentle spoken "
    "sentences. Then ask what name they would like you to use, and wait for "
    "their answer. Do not ask any other setup questions yet, and do not offer "
    "games or topics yet."
)

RETURNING_OPENING_INSTRUCTIONS = (
    f"This conversation is starting up again. Greet them as {DEFAULT_BOT_NAME} "
    "with one short, warm, gentle spoken sentence, and vary the wording. Then "
    "kindly ask whether {name} is there with you, or who you are speaking with. "
    "Do not recap their profile out loud. Once you know who is present, you may "
    "offer a couple of gentle things you could do together."
)

RETURNING_OPENING_UNKNOWN_NAME = (
    f"This conversation is starting up again. Greet them as {DEFAULT_BOT_NAME} "
    "with one short, warm, gentle spoken sentence, and vary the wording. Then "
    "kindly ask who you are speaking with. Do not recap their profile out loud. "
    "Once you know who is present, you may offer a couple of gentle things you "
    "could do together."
)

FIRST_USE_MODULE = """\
## MODULE: First use setup [only while first use is in progress]
This is the first time you are with this person. Stay warm, kind, and unhurried. \
Ask only one question per turn. If an answer is unclear, repeat it back and ask \
if you have it right before moving on.

Work through setup in this order, and do not skip ahead:
1. Introduce yourself as Mio if you have not already, then learn the name of the \
person this device is for. Confirm the name out loud. When you are sure, call \
save_patient_name. That name is important and must be remembered.
2. Ask whether a carer is present in the room. If yes, learn the carer's name, \
make it clear you are noting it as the carer's name, and confirm it. When you \
are sure, call save_carer_name. If no carer is there, say that is perfectly all \
right and continue.
3. Introduce a short Learn Patient moment. Tell them you would just like to ask \
a few questions so you can look after their health and wellbeing a little better. \
Then ask, one at a time: whether they have dementia; a little about their \
lifestyle; their interests and hobbies; how often they exercise in a day; their \
mobility, such as a walker or other mobility issues; and whether there is \
anything specific they would like Mio to do. After each answer you understand, \
call save_patient_notes with what you have learned so far.
4. When those questions are done, call complete_first_use_setup. Then continue \
as a companion: thank them gently, and offer two or three kind things you could \
do together, such as hearing what is on their mind, a favourite memory, music, \
or a light word game.
"""

RETURNING_MODULE = """\
## MODULE: Returning conversation
You have already completed first-use setup with the person this device belongs \
to. Begin with a warm greeting, then make sure you know who is speaking. If you \
know their name, ask whether that person is present. If someone else is speaking, \
including a carer, note that kindly and keep their role in mind. After you know \
who you are with, continue as usual and offer a couple of gentle suggestions if \
they need a starting point. Use the Learn Patient notes silently; do not recite \
them unless they are relevant to what the person just said.
"""

PROFILE_FIELDS = (
    "dementia",
    "lifestyle",
    "interests_and_hobbies",
    "daily_exercise",
    "mobility",
    "mio_preferences",
)


def env_flag(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in TRUE_ENV_VALUES


def first_use_requested(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env_flag(env.get(FIRST_USE_ENV))


def device_user_name(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if environ is None else environ
    value = (env.get(USER_NAME_ENV) or "").strip()
    return value or None


def setup_state_path(
    environ: Mapping[str, str] | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    value = (env.get(SETUP_STATE_PATH_ENV) or "").strip()
    return Path(value or DEFAULT_SETUP_STATE_PATH)


@dataclass
class SetupState:
    completed: bool = False
    patient_name: str | None = None
    carer_name: str | None = None
    patient_profile: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SetupState:
        if not data:
            return cls()
        profile = data.get("patient_profile") or {}
        cleaned_profile = {
            key: str(value).strip()
            for key, value in profile.items()
            if key in PROFILE_FIELDS and str(value).strip()
        }
        return cls(
            completed=bool(data.get("completed")),
            patient_name=_optional_name(data.get("patient_name")),
            carer_name=_optional_name(data.get("carer_name")),
            patient_profile=cleaned_profile,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "patient_name": self.patient_name,
            "carer_name": self.carer_name,
            "patient_profile": dict(self.patient_profile),
        }


def _optional_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_first_use(
    *,
    state: SetupState | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    if state is not None and state.completed:
        return False
    return first_use_requested(environ)


def patient_name_for_device(
    state: SetupState | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    if state is not None and state.patient_name:
        return state.patient_name
    return device_user_name(environ)


def opening_turn_instructions(
    *,
    first_use: bool,
    patient_name: str | None = None,
    setup_completed: bool = False,
) -> str:
    if first_use:
        return FIRST_USE_OPENING_INSTRUCTIONS
    if setup_completed or patient_name:
        if patient_name:
            return RETURNING_OPENING_INSTRUCTIONS.format(name=patient_name)
        return RETURNING_OPENING_UNKNOWN_NAME
    return INITIAL_GREETING_INSTRUCTIONS


def format_setup_context(state: SetupState) -> str | None:
    lines: list[str] = []
    if state.patient_name:
        lines.append(
            f"The person this device is for is named {state.patient_name}."
        )
    if state.carer_name:
        lines.append(
            f"A carer named {state.carer_name} is associated with this person. "
            "NOTE: this is the carer's name, not the patient's."
        )
    labels = {
        "dementia": "Dementia",
        "lifestyle": "Lifestyle",
        "interests_and_hobbies": "Interests and hobbies",
        "daily_exercise": "Daily exercise",
        "mobility": "Mobility",
        "mio_preferences": "What they would like Mio to do",
    }
    for key, label in labels.items():
        value = state.patient_profile.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if _dementia_indicated(state.patient_profile.get("dementia")):
        lines.append(
            "This person has dementia. Follow the Dementia-Aware Interaction "
            "module: short sentences, one question at a time, no memory tests."
        )
    if not lines:
        return None
    bullets = "\n".join(f"- {line}" for line in lines)
    return f"{PROFILE_CONTEXT_PREFIX}\n{bullets}"


def returning_instructions(state: SetupState) -> str:
    parts = [RETURNING_MODULE]
    profile = format_setup_context(state)
    if profile:
        parts.append(profile)
    return "\n\n".join(parts)


def agent_instructions(
    prompt_path: Path,
    *,
    first_use: bool,
    state: SetupState | None = None,
    load_prompt,
) -> str:
    base = load_prompt(prompt_path)
    if first_use:
        return f"{base}\n\n{FIRST_USE_MODULE}"
    if state is not None and (state.completed or state.patient_name):
        return f"{base}\n\n{returning_instructions(state)}"
    return base


def _dementia_indicated(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    if lowered in {"no", "n", "false", "none", "not that i know of"}:
        return False
    positives = ("yes", "dementia", "alzheimer", "cognitive")
    return any(token in lowered for token in positives)


class SetupStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SetupStore:
        return cls(setup_state_path(environ))

    def load(self) -> SetupState:
        if not self.path.is_file():
            return SetupState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SetupState()
        if not isinstance(data, dict):
            return SetupState()
        return SetupState.from_dict(data)

    def save(self, state: SetupState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )


class FirstUseGuide:
    """Persist confirmed first-use facts locally and in Mem0."""

    def __init__(self, store: SetupStore, memory: Any) -> None:
        self._store = store
        self._memory = memory
        self.state = store.load()

    async def save_patient_name(self, name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            return "I still need a name for the person this device is for."
        self.state.patient_name = cleaned
        self._store.save(self.state)
        await self._remember(
            f"The patient's name is {cleaned}. This is important identity "
            "information for the person this Mio device belongs to."
        )
        return f"Saved the patient's name as {cleaned}."

    async def save_carer_name(self, name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            return "I still need the carer's name."
        self.state.carer_name = cleaned
        self._store.save(self.state)
        await self._remember(
            f"The carer's name is {cleaned}. NOTE: this is the carer's name, "
            "not the patient's name."
        )
        return f"Saved the carer's name as {cleaned}."

    async def save_patient_notes(
        self,
        dementia: str | None = None,
        lifestyle: str | None = None,
        interests_and_hobbies: str | None = None,
        daily_exercise: str | None = None,
        mobility: str | None = None,
        mio_preferences: str | None = None,
    ) -> str:
        updates = {
            "dementia": dementia,
            "lifestyle": lifestyle,
            "interests_and_hobbies": interests_and_hobbies,
            "daily_exercise": daily_exercise,
            "mobility": mobility,
            "mio_preferences": mio_preferences,
        }
        saved: list[str] = []
        for key, value in updates.items():
            if value is None or not str(value).strip():
                continue
            self.state.patient_profile[key] = str(value).strip()
            saved.append(key)
        if not saved:
            return "No new Learn Patient notes were saved."
        self._store.save(self.state)
        await self._remember(_profile_memory_text(self.state))
        if self.state.patient_name and all(
            self.state.patient_profile.get(key) for key in PROFILE_FIELDS
        ):
            self.state.completed = True
            self._store.save(self.state)
            return (
                "Saved Learn Patient notes: "
                + ", ".join(saved)
                + ". First-use setup is complete."
            )
        return "Saved Learn Patient notes: " + ", ".join(saved) + "."

    async def complete_setup(self) -> str:
        self.state.completed = True
        self._store.save(self.state)
        return "First-use setup is complete. Continue as a companion."

    async def _remember(self, text: str) -> None:
        remember = getattr(self._memory, "remember_important", None)
        if remember is None:
            remember = getattr(self._memory, "remember_user_message", None)
        if remember is None:
            return
        await remember(text)


def _profile_memory_text(state: SetupState) -> str:
    parts = ["Learn Patient notes for the person this Mio device belongs to."]
    if state.patient_name:
        parts.append(f"Patient name: {state.patient_name}.")
    for key in PROFILE_FIELDS:
        value = state.patient_profile.get(key)
        if value:
            parts.append(f"{key.replace('_', ' ')}: {value}.")
    return " ".join(parts)


def merge_startup_context(*chunks: str | None) -> str | None:
    parts = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]
    if not parts:
        return None
    return "\n\n".join(parts)
