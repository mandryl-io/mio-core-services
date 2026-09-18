from unittest.mock import AsyncMock, Mock

import pytest

from mio_core_services.constants import DEFAULT_MEMORY_USER_ID
from mio_core_services.memory.mem0 import (
    MEM0_CONTEXT_PREFIX,
    Mem0TurnMemory,
    format_mem0_results,
    inject_mem0_turn,
    mem0_enabled,
    memory_user_id,
)


def test_memory_user_id_defaults_when_unset():
    assert memory_user_id({}) == DEFAULT_MEMORY_USER_ID


def test_memory_user_id_uses_env():
    assert memory_user_id({"MIO_MEMORY_USER_ID": "face-abc"}) == "face-abc"


def test_mem0_disabled_without_api_key():
    assert mem0_enabled({}) is False
    assert mem0_enabled({"MEM0_API_KEY": "  "}) is False


def test_mem0_enabled_with_api_key():
    assert mem0_enabled({"MEM0_API_KEY": "m0-test"}) is True


def test_format_mem0_results_uses_memory_field():
    text = format_mem0_results(
        {
            "results": [
                {"memory": "Loves jazz piano"},
                {"text": "Grew up in Adelaide"},
            ]
        }
    )
    assert text is not None
    assert MEM0_CONTEXT_PREFIX in text
    assert "- Loves jazz piano" in text
    assert "- Grew up in Adelaide" in text


def test_format_mem0_results_empty():
    assert format_mem0_results({"results": []}) is None
    assert format_mem0_results(None) is None


@pytest.mark.asyncio
async def test_disabled_memory_is_a_noop():
    memory = Mem0TurnMemory(client=None, user_id="resident-1")
    assert memory.enabled is False
    await memory.remember_user_message("I like tea")
    assert await memory.recall_context("tea") is None


@pytest.mark.asyncio
async def test_remember_and_recall_use_user_id_filter():
    client = AsyncMock()
    client.search.return_value = {
        "results": [{"memory": "Prefers Earl Grey"}]
    }
    memory = Mem0TurnMemory(client=client, user_id="resident-1")

    await memory.remember_user_message("I drink Earl Grey every morning")
    context = await memory.recall_context("What tea do I like?")

    client.add.assert_awaited_once_with(
        [{"role": "user", "content": "I drink Earl Grey every morning"}],
        user_id="resident-1",
    )
    client.search.assert_awaited_once_with(
        "What tea do I like?",
        filters={"user_id": "resident-1"},
    )
    assert context is not None
    assert "Prefers Earl Grey" in context


@pytest.mark.asyncio
async def test_mem0_failures_do_not_raise():
    client = AsyncMock()
    client.add.side_effect = RuntimeError("mem0 down")
    client.search.side_effect = RuntimeError("mem0 down")
    memory = Mem0TurnMemory(client=client, user_id="resident-1")

    await memory.remember_user_message("hello")
    assert await memory.recall_context("hello") is None


@pytest.mark.asyncio
async def test_inject_mem0_turn_adds_system_context():
    client = AsyncMock()
    client.search.return_value = {"results": [{"memory": "Has a son named Tom"}]}
    memory = Mem0TurnMemory(client=client, user_id="resident-1")
    turn_ctx = Mock()

    changed = await inject_mem0_turn(memory, turn_ctx, "How is my son doing?")

    assert changed is True
    kwargs = turn_ctx.add_message.call_args.kwargs
    assert kwargs["role"] == "system"
    assert "Has a son named Tom" in kwargs["content"]


@pytest.mark.asyncio
async def test_inject_mem0_turn_skips_when_disabled():
    turn_ctx = Mock()
    changed = await inject_mem0_turn(
        Mem0TurnMemory(client=None), turn_ctx, "hello"
    )
    assert changed is False
    turn_ctx.add_message.assert_not_called()
