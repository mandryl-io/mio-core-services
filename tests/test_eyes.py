import pytest

from mio_core_services.lighting.eyes import (
    BOTH_SECONDS,
    FLASHES,
    Eyes,
    Step,
    pattern,
)


class FakePin:
    def __init__(self):
        self.value = 0
        self.closed = False

    def close(self):
        self.closed = True


def phases(steps):
    """Split a lap at the point both lamps first light together."""
    for index, step in enumerate(steps):
        if step.left and step.right:
            return steps[:index], steps[index:]
    return steps, []


def test_left_flashes_three_times_then_right():
    flashes, _ = phases(pattern())
    lit = [step for step in flashes if step.left or step.right]
    assert [(s.left, s.right) for s in lit] == [(True, False)] * FLASHES + [
        (False, True)
    ] * FLASHES


def test_no_flash_lights_both_eyes():
    flashes, _ = phases(pattern())
    assert not any(step.left and step.right for step in flashes)


def test_both_phase_lasts_exactly_the_requested_time():
    _, both = phases(pattern(both_seconds=3.0))
    assert sum(step.seconds for step in both) == pytest.approx(3.0)


def test_both_phase_is_trimmed_not_overrun():
    """An awkward duration must not round up to a whole blink cycle."""
    _, both = phases(pattern(both_seconds=1.0, blink_on=0.3, blink_off=0.3))
    assert sum(step.seconds for step in both) == pytest.approx(1.0)
    assert both[-1].seconds < 0.3


def test_both_phase_alternates_on_and_off():
    _, both = phases(pattern())
    states = [(step.left, step.right) for step in both]
    assert states[0] == (True, True)
    for previous, current in zip(states, states[1:]):
        assert previous != current
    assert all(left == right for left, right in states)


def test_both_phase_starts_lit():
    _, both = phases(pattern())
    assert both[0].left and both[0].right


def test_flash_count_is_configurable():
    flashes, _ = phases(pattern(flashes=5))
    assert sum(1 for step in flashes if step.left and not step.right) == 5


def test_every_step_has_positive_duration():
    assert all(step.seconds > 0 for step in pattern())


def test_lap_length_is_the_sum_of_its_parts():
    steps = pattern(flashes=3, flash_on=0.1, flash_off=0.2, gap=0.5,
                    both_seconds=3.0)
    # 3 flashes = 3 on + 2 off, per eye; two gaps; then the both phase.
    expected = 2 * (3 * 0.1 + 2 * 0.2) + 2 * 0.5 + 3.0
    assert sum(step.seconds for step in steps) == pytest.approx(expected)


def test_zero_gap_removes_the_pauses():
    steps = pattern(gap=0)
    dark = [s for s in steps if not s.left and not s.right]
    assert all(step.seconds == pytest.approx(0.18) for step in dark[: FLASHES - 1])


def test_default_both_phase_is_three_seconds():
    _, both = phases(pattern())
    assert sum(step.seconds for step in both) == pytest.approx(BOTH_SECONDS)


def test_eyes_drive_both_pins():
    left, right = FakePin(), FakePin()
    eyes = Eyes(left, right)
    eyes.set(True, False)
    assert (left.value, right.value) == (1, 0)
    eyes.set(False, True)
    assert (left.value, right.value) == (0, 1)


def test_off_clears_both():
    left, right = FakePin(), FakePin()
    eyes = Eyes(left, right)
    eyes.set(True, True)
    eyes.off()
    assert (left.value, right.value) == (0, 0)


def test_close_releases_both_pins():
    left, right = FakePin(), FakePin()
    Eyes(left, right).close()
    assert left.closed and right.closed


def test_step_is_comparable():
    assert Step(True, False, 0.1) == Step(True, False, 0.1)


def test_alternating_never_lights_both_eyes():
    from mio_core_services.lighting.eyes import alternating

    assert not any(step.left and step.right for step in alternating())


def test_alternating_gives_each_eye_three_seconds():
    from mio_core_services.lighting.eyes import alternating

    steps = alternating(each_seconds=3.0)
    assert sum(step.seconds for step in steps) == pytest.approx(6.0)

    # Each eye's turn is a contiguous half of the lap: everything up to the
    # first right-hand step belongs to the left eye, and vice versa.
    first_right = next(i for i, step in enumerate(steps) if step.right)
    assert sum(s.seconds for s in steps[:first_right]) == pytest.approx(3.0)
    assert sum(s.seconds for s in steps[first_right:]) == pytest.approx(3.0)


def test_alternating_left_leads_then_right():
    from mio_core_services.lighting.eyes import alternating

    steps = alternating()
    lit = [s for s in steps if s.left or s.right]
    half = len(lit) // 2
    assert all(s.left and not s.right for s in lit[:half])
    assert all(s.right and not s.left for s in lit[half:])


def test_alternating_phase_is_trimmed_to_length():
    from mio_core_services.lighting.eyes import alternating

    steps = alternating(each_seconds=1.0, blink_on=0.3, blink_off=0.3)
    assert sum(s.seconds for s in steps) == pytest.approx(2.0)


def test_alternating_actually_blinks_rather_than_holding():
    from mio_core_services.lighting.eyes import alternating

    steps = alternating(each_seconds=3.0, blink_on=0.15, blink_off=0.15)
    assert len([s for s in steps if s.left]) == 10  # 3s / 0.3s cycle, lit half


def test_alternating_steps_all_positive():
    from mio_core_services.lighting.eyes import alternating

    assert all(step.seconds > 0 for step in alternating())
