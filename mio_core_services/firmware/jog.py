"""Shared timing for arrow-key jogging, and the speed that keeps it smooth."""

# How often a held key advances the goal, and how long after the last keypress
# the servo is considered to have stopped.
JOG_DT = 0.02
HOLD_DT = 0.12

# Jogging re-issues the goal every JOG_DT, so the servo must still be
# travelling when the next one lands. Commanding much faster than the goal
# actually advances makes it sprint to each one, stop, and wait -- 50 times a
# second, which reads as jitter and is worst on a gravity-loaded axis.
JOG_SPEED_HEADROOM = 1.25
MIN_JOG_SPEED = 50


def jog_speed_for(step: int) -> int:
    """Tracking speed matched to how fast jogging advances the goal."""
    return max(MIN_JOG_SPEED, round(step / JOG_DT * JOG_SPEED_HEADROOM))
