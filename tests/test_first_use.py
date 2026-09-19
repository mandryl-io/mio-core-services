from unittest.mock import AsyncMock

import pytest

from mio_core_services.constants import INITIAL_GREETING_INSTRUCTIONS
from mio_core_services.first_use import (
    FIRST_USE_MODULE,
    FIRST_USE_OPENING_INSTRUCTIONS,
    PROFILE_CONTEXT_PREFIX,
    RETURNING_OPENING_INSTRUCTIONS,
    FirstUseGuide,
    SetupState,
    SetupStore,
    agent_instructions,
    first_use_requested,
    format_setup_context,
    is_first_use,
    merge_startup_context,
    opening_turn_instructions,
    patient_name_for_device,
)


def test_first_use_requested_reads_truthy_env():
    assert first_use_requested({"MIO_FIRST_USE": "true"}) is True
    assert first_use_requested({"MIO_FIRST_USE": "1"}) is True
    assert first_use_requested({"MIO_FIRST_USE": "yes"}) is True
    assert first_use_requested({"MIO_FIRST_USE": "on"}) is True
    assert first_use_requested({}) is False
    assert first_use_requested({"MIO_FIRST_USE": "false"}) is False


def test_completed_setup_is_not_first_use():
    state = SetupState(completed=True, patient_name="Margaret")
    assert is_first_use(state=state, environ={"MIO_FIRST_USE": "true"}) is False


def test_opening_turn_uses_first_use_intro():
    assert (
        opening_turn_instructions(first_use=True)
        == FIRST_USE_OPENING_INSTRUCTIONS
    )
    assert "introduce yourself as mio" in FIRST_USE_OPENING_INSTRUCTIONS.lower()


def test_opening_turn_asks_if_named_person_is_present():
    text = opening_turn_instructions(
        first_use=False,
        patient_name="Margaret",
        setup_completed=True,
    )
    assert text == RETURNING_OPENING_INSTRUCTIONS.format(name="Margaret")
    assert "margaret" in text.lower()
    assert "speaking with" in text.lower()


def test_opening_turn_keeps_default_when_setup_has_not_happened():
    assert (
        opening_turn_instructions(first_use=False)
        == INITIAL_GREETING_INSTRUCTIONS
    )


def test_patient_name_prefers_saved_state_over_env():
    state = SetupState(patient_name="Margaret")
    assert (
        patient_name_for_device(state, {"MIO_USER_NAME": "Env Name"})
        == "Margaret"
    )
    assert patient_name_for_device(None, {"MIO_USER_NAME": "Env Name"}) == (
        "Env Name"
    )


def test_setup_store_roundtrip(tmp_path):
    store = SetupStore(tmp_path / "state.json")
    state = SetupState(
        completed=True,
        patient_name="Margaret",
        carer_name="James",
        patient_profile={"mobility": "uses a walker"},
    )
    store.save(state)
    loaded = store.load()
    assert loaded.completed is True
    assert loaded.patient_name == "Margaret"
    assert loaded.carer_name == "James"
    assert loaded.patient_profile["mobility"] == "uses a walker"


def test_format_setup_context_includes_carer_note_and_dementia_guidance():
    text = format_setup_context(
        SetupState(
            patient_name="Margaret",
            carer_name="James",
            patient_profile={
                "dementia": "yes, some days are harder",
                "interests_and_hobbies": "garden and piano",
            },
        )
    )
    assert text is not None
    assert PROFILE_CONTEXT_PREFIX in text
    assert "Margaret" in text
    assert "carer's name" in text
    assert "Dementia-Aware" in text
    assert "garden and piano" in text


def test_agent_instructions_append_first_use_module(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Be kind.", encoding="utf-8")
    text = agent_instructions(
        prompt,
        first_use=True,
        load_prompt=lambda path: path.read_text(encoding="utf-8"),
    )
    assert "Be kind." in text
    assert FIRST_USE_MODULE in text
    assert "Learn Patient" in text


@pytest.mark.asyncio
async def test_guide_saves_names_and_profile_to_mem0(tmp_path):
    memory = AsyncMock()
    guide = FirstUseGuide(SetupStore(tmp_path / "state.json"), memory)

    await guide.save_patient_name("  Margaret  ")
    await guide.save_carer_name("James")
    await guide.save_patient_notes(
        dementia="no",
        lifestyle="quiet mornings",
        interests_and_hobbies="the wireless",
        daily_exercise="a short walk",
        mobility="uses a walker",
        mio_preferences="remind me about tea",
    )
    await guide.complete_setup()

    saved = SetupStore(tmp_path / "state.json").load()
    assert saved.patient_name == "Margaret"
    assert saved.carer_name == "James"
    assert saved.completed is True
    assert saved.patient_profile["mobility"] == "uses a walker"
    important = [
        call.args[0] for call in memory.remember_important.await_args_list
    ]
    assert any("patient's name is Margaret" in item for item in important)
    assert any("carer's name is James" in item for item in important)
    assert any("Learn Patient notes" in item for item in important)


def test_merge_startup_context_skips_empty():
    assert merge_startup_context(None, "  ") is None
    assert merge_startup_context("local", "mem0") == "local\n\nmem0"
