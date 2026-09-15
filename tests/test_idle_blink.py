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


def test_open_mean_sits_between_human_and_sleepy(settings):
    # Human IBI ~6.4 s; 1 SD slow was 8.3 s and felt too long.
    assert 6.4 < settings.open_mean < 8.3
    assert settings.open_spread == pytest.approx(2.4)


def test_blink_duration_stays_near_the_human_median(settings):
    assert 0.18 <= settings.blink_mean <= 0.22
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
