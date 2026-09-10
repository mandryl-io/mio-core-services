from mio_core_services.perception.identity import parse_spoken_name


def test_explicit_name_phrases():
    assert parse_spoken_name("My name is Sarah").name == "Sarah"
    assert parse_spoken_name("call me Dillon").name == "Dillon"


def test_short_im_utterance():
    assert parse_spoken_name("I'm Sarah").name == "Sarah"
    assert parse_spoken_name("I am Pat.").name == "Pat"


def test_correction_with_replacement():
    spoken = parse_spoken_name("I'm not Dillon, I'm Sarah")

    assert spoken is not None
    assert spoken.rejected == "Dillon"
    assert spoken.name == "Sarah"


def test_copular_predicates_are_not_names():
    assert parse_spoken_name("I'm tired") is None
    assert parse_spoken_name("I'm not sure") is None
    assert parse_spoken_name("I miss her so much") is None
    assert parse_spoken_name("I'm not feeling well") is None
