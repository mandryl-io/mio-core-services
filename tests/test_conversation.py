from pathlib import Path
from unittest.mock import Mock

import pytest

from mio_core_services.constants import (
    DEFAULT_CONVERSATION_LLM_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_INSTRUCTIONS,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.conversation import (
    REQUIRED_ENV_VARS,
    create_session,
    load_system_prompt,
    require_env,
    system_prompt_path,
)


def _clear_required_env(monkeypatch) -> None:
    for name in REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_system_prompt_argument(monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["conversation.py", "--system-prompt", "prompts/custom.md"]
    )
    assert system_prompt_path() == Path("prompts/custom.md")


def test_load_system_prompt(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("# Mio\n\nBe kind.\n", encoding="utf-8")
    assert load_system_prompt(prompt_path) == "# Mio\n\nBe kind."


def test_require_env_missing_keys_raise(monkeypatch):
    _clear_required_env(monkeypatch)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        require_env()


@pytest.mark.parametrize("missing", REQUIRED_ENV_VARS)
def test_require_env_each_missing_key_raises(monkeypatch, missing):
    _clear_required_env(monkeypatch)
    for name in REQUIRED_ENV_VARS:
        if name != missing:
            monkeypatch.setenv(name, "present")
    with pytest.raises(ValueError, match=missing):
        require_env()


def test_require_env_all_present_does_not_raise(monkeypatch):
    for name in REQUIRED_ENV_VARS:
        monkeypatch.setenv(name, "present")
    require_env()


def test_create_session_uses_conversation_models(monkeypatch):
    captured = {}

    class FakeSTT:
        def __init__(self, **kwargs):
            captured["stt"] = kwargs

    class FakeLLM:
        def __init__(self, **kwargs):
            captured["llm"] = kwargs

    class FakeTTS:
        def __init__(self, **kwargs):
            captured["tts"] = kwargs

    class FakeSession:
        def __init__(self, **kwargs):
            captured["session"] = kwargs

    monkeypatch.setattr("mio_core_services.conversation.openai.STT", FakeSTT)
    monkeypatch.setattr("mio_core_services.conversation.anthropic.LLM", FakeLLM)
    monkeypatch.setattr("mio_core_services.conversation.openai.TTS", FakeTTS)
    monkeypatch.setattr(
        "mio_core_services.conversation.inference.TurnDetector", Mock
    )
    monkeypatch.setattr(
        "mio_core_services.conversation.AgentSession", FakeSession
    )

    create_session()

    assert captured["stt"]["model"] == DEFAULT_STT_MODEL
    assert captured["stt"]["language"] == "en"
    assert captured["llm"]["model"] == DEFAULT_CONVERSATION_LLM_MODEL
    assert captured["tts"]["model"] == DEFAULT_TTS_MODEL
    assert captured["tts"]["voice"] == DEFAULT_TTS_VOICE
    assert captured["tts"]["instructions"] == DEFAULT_TTS_INSTRUCTIONS
    assert captured["session"]["stt"].__class__.__name__ == "FakeSTT"
    assert captured["session"]["llm"].__class__.__name__ == "FakeLLM"
    assert captured["session"]["tts"].__class__.__name__ == "FakeTTS"
    assert "turn_handling" in captured["session"]
