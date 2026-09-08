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


class VelocityJog:
    """Jog by commanding travel toward a limit, rather than micro-stepping.

    Re-issuing a goal every JOG_DT makes the servo accelerate and decelerate
    fifty times a second, which buzzes and never reaches a steady speed. Here a
    held key sends one goal at the limit in that direction and lets the servo's
    own speed control cruise; releasing it stops at wherever it actually is.
    """

    def __init__(self, bus, servo_id, minimum, maximum, speed, acc=30):
        self.bus = bus
        self.servo_id = servo_id
        self.minimum = minimum
        self.maximum = maximum
        self.speed = speed
        self.bus.prepare(servo_id=servo_id, speed=speed, acc=acc)
        self._direction = 0

    @property
    def direction(self) -> int:
        return self._direction

    def steer(self, direction: int) -> None:
        """Send a goal only when the direction actually changes."""
        if direction == self._direction:
            return
        self._direction = direction
        if direction == 0:
            self.stop()
        else:
            goal = self.maximum if direction > 0 else self.minimum
            self.bus.set_goal(goal, servo_id=self.servo_id)

    def stop(self) -> int:
        """Halt at the current position and return it."""
        try:
            position = self.bus.position(servo_id=self.servo_id)
        except TimeoutError:
            return -1
        self.bus.set_goal(position, servo_id=self.servo_id)
        self._direction = 0
        return position

    def read(self) -> int:
        try:
            return self.bus.position(servo_id=self.servo_id)
        except TimeoutError:
            return -1
