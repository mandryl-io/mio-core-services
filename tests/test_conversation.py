import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from mio_core_services.constants import (
    DEFAULT_CONVERSATION_LLM_MODEL,
    DEFAULT_CONVERSATION_LLM_REASONING_EFFORT,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_INSTRUCTIONS,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.conversation import (
    REQUIRED_ENV_VARS,
    apply_os_level_baseten_api_key,
    create_session,
    load_system_prompt,
    require_env,
    system_prompt_path,
)


def _clear_required_env(monkeypatch) -> None:
    monkeypatch.setattr(
        "mio_core_services.conversation._OS_LEVEL_ENV_FILES", ()
    )
    for name in REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_system_prompt_environment(monkeypatch):
    monkeypatch.setenv("MIO_SYSTEM_PROMPT_PATH", "prompts/custom.md")
    assert system_prompt_path() == Path("prompts/custom.md")


def test_load_system_prompt(tmp_path):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("# Mio\n\nBe kind.\n", encoding="utf-8")
    assert load_system_prompt(prompt_path) == "# Mio\n\nBe kind."


def test_require_env_missing_keys_raise(monkeypatch):
    _clear_required_env(monkeypatch)
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
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
    _clear_required_env(monkeypatch)
    for name in REQUIRED_ENV_VARS:
        monkeypatch.setenv(name, "present")
    require_env()


def test_os_level_baseten_key_fills_empty_process_env(tmp_path):
    env_file = tmp_path / "environment"
    env_file.write_text('BASETEN_API_KEY="os-root-key"\n', encoding="utf-8")
    environ = {}
    apply_os_level_baseten_api_key(environ=environ, env_files=(env_file,))
    assert environ["BASETEN_API_KEY"] == "os-root-key"


def test_process_baseten_key_wins_over_os_file(tmp_path):
    env_file = tmp_path / "environment"
    env_file.write_text("BASETEN_API_KEY=from-file\n", encoding="utf-8")
    environ = {"BASETEN_API_KEY": "from-process"}
    apply_os_level_baseten_api_key(environ=environ, env_files=(env_file,))
    assert environ["BASETEN_API_KEY"] == "from-process"


def test_require_env_accepts_os_level_baseten_key(tmp_path, monkeypatch):
    _clear_required_env(monkeypatch)
    env_file = tmp_path / "environment"
    env_file.write_text("BASETEN_API_KEY=os-root-key\n", encoding="utf-8")
    monkeypatch.setattr(
        "mio_core_services.conversation._OS_LEVEL_ENV_FILES", (env_file,)
    )
    for name in REQUIRED_ENV_VARS:
        if name != "BASETEN_API_KEY":
            monkeypatch.setenv(name, "present")
    require_env()
    assert os.environ["BASETEN_API_KEY"] == "os-root-key"


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

    class FakeVAD:
        @staticmethod
        def load():
            captured["vad"] = True
            return "fake-vad"

    monkeypatch.setenv("BASETEN_API_KEY", "test-baseten-key")
    monkeypatch.setattr("mio_core_services.conversation.deepgram.STT", FakeSTT)
    monkeypatch.setattr("mio_core_services.conversation.baseten.LLM", FakeLLM)
    monkeypatch.setattr("mio_core_services.conversation.openai.TTS", FakeTTS)
    monkeypatch.setattr("mio_core_services.conversation.silero.VAD", FakeVAD)
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
    assert captured["llm"]["api_key"] == "test-baseten-key"
    assert (
        captured["llm"]["reasoning_effort"]
        == DEFAULT_CONVERSATION_LLM_REASONING_EFFORT
    )
    assert captured["tts"]["model"] == DEFAULT_TTS_MODEL
    assert captured["tts"]["voice"] == DEFAULT_TTS_VOICE
    assert captured["tts"]["instructions"] == DEFAULT_TTS_INSTRUCTIONS
    assert captured["session"]["stt"].__class__.__name__ == "FakeSTT"
    assert captured["session"]["llm"].__class__.__name__ == "FakeLLM"
    assert captured["session"]["tts"].__class__.__name__ == "FakeTTS"
    assert captured["session"]["vad"] == "fake-vad"
    turn_handling = captured["session"]["turn_handling"]
    assert turn_handling["interruption"]["enabled"] is True
    assert turn_handling["interruption"]["mode"] == "adaptive"
    assert captured["vad"] is True
