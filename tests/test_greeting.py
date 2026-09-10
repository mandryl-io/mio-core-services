from mio_core_services.constants import DEFAULT_BOT_NAME, DEFAULT_INITIAL_MESSAGE
from mio_core_services.perception.greeting import (
    GREETING_PREFIX,
    greeting_developer_message,
    is_greeting_message,
    join_names,
    spoken_greeting,
)


def test_join_one_two_and_many_names():
    assert join_names(["Dillon"]) == "Dillon"
    assert join_names(["Dillon", "Sarah"]) == "Dillon and Sarah"
    assert join_names(["Dillon", "Sarah", "Pat"]) == "Dillon, Sarah, and Pat"


def test_spoken_greeting_without_names_keeps_the_generic_line():
    assert spoken_greeting(DEFAULT_INITIAL_MESSAGE, []) == DEFAULT_INITIAL_MESSAGE


def test_spoken_greeting_names_only_the_known_people():
    assert (
        spoken_greeting(DEFAULT_INITIAL_MESSAGE, ["Dillon"])
        == f"Hi, Dillon. I'm {DEFAULT_BOT_NAME}. How are you today?"
    )
    assert (
        spoken_greeting(DEFAULT_INITIAL_MESSAGE, ["Dillon", "Sarah"])
        == f"Hi, Dillon and Sarah. I'm {DEFAULT_BOT_NAME}. How are you today?"
    )


def test_greeting_developer_message_is_detectable():
    message = greeting_developer_message("Hi, I'm Mio. How are you today?")

    assert is_greeting_message(message)
    assert message["content"].startswith(GREETING_PREFIX)
    assert not is_greeting_message({"role": "system", "content": "People facing the camera:"})
