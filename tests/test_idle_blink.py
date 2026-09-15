import random
from pathlib import Path

import pytest

from mio_core_services.lighting.idle_blink import (
    DEFAULT_SETTINGS,
    fade_level,
    load_settings,
    next_blink,
    next_open,
)


@pytest.fixture
def settings():
    return load_settings()


def test_default_settings_file_exists():
    assert DEFAULT_SETTINGS.is_file()


def test_slow_open_is_one_sd_below_human_rate(settings):
    # 10.3 - 3.1 = 7.2 blinks/min → 8.3 s between blinks.
    assert settings.open_mean == pytest.approx(8.3, abs=0.05)
    assert settings.open_spread == pytest.approx(2.4)


def test_slow_blink_is_one_sd_above_human_duration(settings):
    # 0.18 + 0.032 = 0.212 s. Longer eyelid, not a shorter one.
    assert settings.blink_mean == pytest.approx(0.212, abs=0.002)
    assert settings.blink_spread == pytest.approx(0.032)


def test_blink_stays_in_configured_range(settings):
    random.seed(0)
    for _ in range(200):
        assert settings.blink_min <= next_blink(settings) <= settings.blink_max


def test_open_stays_in_configured_range(settings):
    random.seed(0)
    for _ in range(200):
        assert settings.open_min <= next_open(settings) <= settings.open_max


def test_noise_actually_varies(settings):
    random.seed(1)
    blinks = {round(next_blink(settings), 4) for _ in range(40)}
    opens = {round(next_open(settings), 3) for _ in range(40)}
    assert len(blinks) > 1
    assert len(opens) > 1


def test_load_settings_reads_a_file(tmp_path: Path):
    path = tmp_path / "blink.yaml"
    path.write_text(
        "blink_mean: 0.3\nblink_spread: 0.01\nblink_min: 0.2\nblink_max: 0.4\n"
        "open_mean: 9\nopen_spread: 1\nopen_min: 5\nopen_max: 12\n"
    )
    loaded = load_settings(path)
    assert loaded.open_mean == 9
    assert loaded.blink_mean == 0.3


def test_fade_starts_and_ends_on_the_targets():
    assert fade_level(1.0, 0.0, 0.0) == 1.0
    assert fade_level(1.0, 0.0, 1.0) == 0.0
    assert fade_level(0.0, 1.0, 0.0) == 0.0
    assert fade_level(0.0, 1.0, 1.0) == 1.0


def test_fade_is_halfway_at_the_midpoint():
    assert fade_level(1.0, 0.0, 0.5) == pytest.approx(0.5)
    assert fade_level(0.0, 1.0, 0.5) == pytest.approx(0.5)
