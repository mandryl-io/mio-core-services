import random

from mio_core_services.lighting.idle_blink import (
    BLINK_MAX,
    BLINK_MIN,
    OPEN_MAX,
    OPEN_MIN,
    next_blink,
    next_open,
)


def test_blink_stays_in_human_range():
    random.seed(0)
    for _ in range(200):
        assert BLINK_MIN <= next_blink() <= BLINK_MAX


def test_open_stays_in_human_range():
    random.seed(0)
    for _ in range(200):
        assert OPEN_MIN <= next_open() <= OPEN_MAX


def test_noise_actually_varies():
    random.seed(1)
    blinks = {round(next_blink(), 4) for _ in range(40)}
    opens = {round(next_open(), 3) for _ in range(40)}
    assert len(blinks) > 1
    assert len(opens) > 1
