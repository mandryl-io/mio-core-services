from unittest.mock import Mock

import pytest

from mio_core_services.constants import (
    DEFAULT_CONVERSATION_LLM_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_VOICE,
)
from mio_core_services.conversation import create_session, require_env

REQUIRED = (
    "OPENAI_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


def _clear_required_env(monkeypatch) -> None:
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)


def test_require_env_missing_keys_raise(monkeypatch):
    _clear_required_env(monkeypatch)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        require_env()


@pytest.mark.parametrize("missing", REQUIRED)
def test_require_env_each_missing_key_raises(monkeypatch, missing):
    _clear_required_env(monkeypatch)
    for name in REQUIRED:
        if name != missing:
            monkeypatch.setenv(name, "present")
    with pytest.raises(ValueError, match=missing):
        require_env()


def test_require_env_all_present_does_not_raise(monkeypatch):
    for name in REQUIRED:
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
    monkeypatch.setattr("mio_core_services.conversation.openai.LLM", FakeLLM)
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
    assert captured["tts"]["model"] == "tts-1"
    assert captured["tts"]["voice"] == DEFAULT_TTS_VOICE
    assert captured["session"]["stt"].__class__.__name__ == "FakeSTT"
    assert captured["session"]["llm"].__class__.__name__ == "FakeLLM"
    assert captured["session"]["tts"].__class__.__name__ == "FakeTTS"
    assert "turn_handling" in captured["session"]
