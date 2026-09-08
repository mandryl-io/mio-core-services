"""Shared timing for arrow-key jogging, and the speed that keeps it smooth."""

import time

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

    def __init__(
        self, bus, servo_id, minimum, maximum, speed, acc=60, limp_after=None
    ):
        self.bus = bus
        self.servo_id = servo_id
        self.minimum = minimum
        self.maximum = maximum
        self.speed = speed
        self.acc = acc
        self.limp_after = limp_after
        self.bus.prepare(servo_id=servo_id, speed=speed, acc=acc)
        self._direction = 0
        self._limped = False
        self._stopped_at = 0.0

    def _lead(self) -> int:
        """How far the servo travels between reading a position and stopping.

        Commanding the position just read makes it reverse into that point,
        which is the bounce. Aiming this far ahead lets it decelerate forward
        into the goal instead. Acceleration is in units of 100 ticks/s^2.
        """
        accel = max(1, self.acc) * 100
        braking = self.speed**2 / (2 * accel)
        latency = self.speed * 0.02
        return int(braking + latency)

    @property
    def direction(self) -> int:
        return self._direction

    def steer(self, direction: int) -> None:
        """Send a goal only when the direction actually changes."""
        if direction == self._direction:
            return
        if direction != 0 and self._limped:
            self.wake()
        if direction == 0:
            self.stop()
            self._stopped_at = time.monotonic()
        else:
            self._direction = direction
            goal = self.maximum if direction > 0 else self.minimum
            self.bus.set_goal(goal, servo_id=self.servo_id)

    def tick(self, now: float) -> None:
        """Cut torque once it has been still long enough, if asked to."""
        if self.limp_after is None or self._limped or self._direction != 0:
            return
        if self._stopped_at and now - self._stopped_at > self.limp_after:
            self.limp()

    def stop(self) -> int:
        """Coast to a halt ahead of the current position, and return the goal."""
        travelling = self._direction
        self._direction = 0
        try:
            position = self.bus.position(servo_id=self.servo_id)
        except TimeoutError:
            return -1
        goal = position + travelling * self._lead()
        goal = max(self.minimum, min(self.maximum, goal))
        self.bus.set_goal(goal, servo_id=self.servo_id)
        return goal

    def limp(self) -> None:
        """Cut torque, so a servo the mechanism can hold stops hunting."""
        self._direction = 0
        self._limped = True
        try:
            self.bus.enable_torque(self.servo_id, False)
        except (TimeoutError, OSError):
            pass

    def wake(self) -> None:
        """Re-engage after limp, before moving again."""
        self._limped = False
        self.bus.prepare(servo_id=self.servo_id, speed=self.speed, acc=self.acc)

    def read(self) -> int:
        try:
            return self.bus.position(servo_id=self.servo_id)
        except TimeoutError:
            return -1
