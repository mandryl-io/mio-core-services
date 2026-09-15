import itertools

from mio_core_services.lighting.color_cycle import (
    LEVELS,
    SEQUENCE,
    Beat,
    _mix,
    plan,
)
from mio_core_services.lighting.pixels import Strip


class FakeBuf:
    """Stands in for a PixelBuf, recording what was written and shown."""

    def __init__(self, count: int = 1):
        self.pixels = [(0, 0, 0)] * count
        self.frames: list[tuple] = []

    def __setitem__(self, index, value):
        self.pixels[index] = value

    def show(self):
        self.frames.append(tuple(self.pixels))


def test_sequence_is_primaries_then_spectrum():
    names = [name for name, _ in SEQUENCE]
    assert names[:3] == ["red", "green", "blue"]
    assert names[3:] == [
        "red", "orange", "yellow", "green", "blue", "indigo", "violet",
    ]


def test_brightness_changes_on_every_transition():
    beats = list(itertools.islice(plan(), 200))
    for previous, beat in zip(beats, beats[1:]):
        assert previous.brightness != beat.brightness, f"repeat at {beat.name}"


def test_brightness_offset_carries_across_laps():
    """The ladder must not reset each lap, or the pairing never shifts."""
    beats = list(plan(laps=2))
    first, second = beats[: len(SEQUENCE)], beats[len(SEQUENCE) :]
    assert [b.name for b in first] == [b.name for b in second]
    assert [b.brightness for b in first] != [b.brightness for b in second]


def test_pairing_repeats_only_after_both_cycles_close():
    """Coprime lengths, so the whole pattern takes 70 beats to come round.

    Individual pairings can recur sooner -- red sits in both the primaries and
    the spectrum -- so the invariant is on the sequence, not on single beats.
    """
    period = len(SEQUENCE) * len(LEVELS)
    beats = list(itertools.islice(plan(), period * 2))
    assert beats[:period] == beats[period:]
    for offset in range(1, period):
        assert beats[:period] != beats[offset : offset + period]


def test_each_colour_is_seen_at_several_brightnesses():
    beats = list(itertools.islice(plan(), len(SEQUENCE) * len(LEVELS)))
    for name in {name for name, _ in SEQUENCE}:
        levels = {beat.brightness for beat in beats if beat.name == name}
        assert len(levels) > 1, f"{name} never changes brightness"


def test_laps_zero_runs_forever():
    assert len(list(itertools.islice(plan(laps=0), 500))) == 500


def test_finite_laps_terminate():
    assert len(list(plan(laps=3))) == 3 * len(SEQUENCE)


def test_levels_stay_within_range():
    assert all(0.0 < level <= 1.0 for level in LEVELS)


def test_mix_interpolates_endpoints():
    assert _mix((0, 0, 0), (255, 0, 0), 0.0) == (0, 0, 0)
    assert _mix((0, 0, 0), (255, 0, 0), 1.0) == (255, 0, 0)
    assert _mix((0, 0, 0), (100, 200, 40), 0.5) == (50, 100, 20)


def test_full_brightness_is_unchanged_by_gamma():
    buf = FakeBuf()
    Strip(buf, 1, gamma=2.2, ceiling=1.0).show((255, 0, 0), 1.0)
    assert buf.frames[-1] == ((255, 0, 0),)


def test_gamma_dims_further_than_a_linear_scale():
    """Half brightness should emit well under half the light, or it looks flat."""
    linear = FakeBuf()
    Strip(linear, 1, gamma=0, ceiling=1.0).show((255, 255, 255), 0.5)
    corrected = FakeBuf()
    Strip(corrected, 1, gamma=2.2, ceiling=1.0).show((255, 255, 255), 0.5)
    assert corrected.frames[-1][0][0] < linear.frames[-1][0][0]


def test_ceiling_caps_every_level():
    buf = FakeBuf()
    Strip(buf, 1, gamma=0, ceiling=0.25).show((255, 255, 255), 1.0)
    assert buf.frames[-1] == ((64, 64, 64),)


def test_brightness_is_clamped():
    buf = FakeBuf()
    strip = Strip(buf, 1, gamma=0, ceiling=1.0)
    strip.show((255, 0, 0), 5.0)
    strip.show((255, 0, 0), -1.0)
    assert buf.frames[0] == ((255, 0, 0),)
    assert buf.frames[1] == ((0, 0, 0),)


def test_every_pixel_gets_the_colour():
    buf = FakeBuf(4)
    Strip(buf, 4, gamma=0, ceiling=1.0).show((0, 0, 255), 1.0)
    assert buf.frames[-1] == ((0, 0, 255),) * 4


def test_off_writes_black_once():
    buf = FakeBuf(2)
    Strip(buf, 2, gamma=0, ceiling=1.0).off()
    assert buf.frames == [((0, 0, 0), (0, 0, 0))]


def test_beat_is_hashable_for_comparison():
    assert Beat("red", (255, 0, 0), 1.0) == Beat("red", (255, 0, 0), 1.0)
