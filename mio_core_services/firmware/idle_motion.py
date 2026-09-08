"""Natural idle head motion, held inside the calibrated travel limits.

Movement is generated as a sequence of gaze shifts: mostly small glances near
centre, occasionally a larger look, sometimes a nod, with varied speed and
dwell so it does not read as a machine sweeping. Every goal is clamped to the
calibrated range, and by default the servos' own EEPROM limits are verified
first so a bug here still cannot drive the mechanism into a stop.
"""

from __future__ import annotations

import argparse
import random
import signal
import sys
import time
from dataclasses import dataclass

from mio_core_services.firmware.apply_limits import check
from mio_core_services.firmware.servo_zeros_io import degrees_from_ticks
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import ServoRange, load_zeros

ARRIVE_TOLERANCE = 25
POLL = 0.05


@dataclass(frozen=True)
class Axis:
    """One servo's usable travel, already inset from the calibrated limits."""

    servo_id: int
    zero: int
    low: int
    high: int

    @classmethod
    def build(cls, servo_id: int, rng: ServoRange, margin: float) -> Axis:
        below = rng.zero - rng.min
        above = rng.max - rng.zero
        low = rng.zero - round(below * (1.0 - margin))
        high = rng.zero + round(above * (1.0 - margin))
        return cls(servo_id, rng.zero, low, high)

    def clamp(self, position: int) -> int:
        return max(self.low, min(self.high, position))

    def sample(self, spread: float, floor: float = 0.0) -> int:
        """A position near zero. spread scales the typical stray, floor the least.

        Without a floor a gaussian keeps returning near-zero offsets, which look
        like twitches rather than decisions.
        """
        offset = random.gauss(0.0, spread)
        if floor and abs(offset) < floor:
            offset = floor if offset >= 0 else -floor
        reach = (self.high - self.zero) if offset >= 0 else (self.zero - self.low)
        return self.clamp(self.zero + round(offset * reach))


class Stopping:
    """Latches on SIGINT or SIGTERM so systemd can stop this cleanly."""

    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, *_: object) -> None:
        self.requested = True


def _travel(
    bus: STS3215Bus,
    axes: dict[int, Axis],
    goals: dict[int, int],
    speed: int,
    stopping: Stopping,
    acc: int = 30,
    timeout: float = 6.0,
) -> None:
    safe = {}
    for servo_id, goal in goals.items():
        axis = axes[servo_id]
        clamped = axis.clamp(goal)
        if clamped != goal:  # a bug upstream, not an expected path
            print(f"  clamped servo {servo_id}: {goal} -> {clamped}", file=sys.stderr)
        safe[servo_id] = clamped

    for servo_id in safe:
        bus.prepare(servo_id=servo_id, speed=speed, acc=acc)
    bus.set_goals(safe)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not stopping.requested:
        time.sleep(POLL)
        try:
            if all(
                abs(bus.position(servo_id=servo_id) - goal) <= ARRIVE_TOLERANCE
                for servo_id, goal in safe.items()
            ):
                return
        except TimeoutError:
            continue


def _dwell(seconds: float, stopping: Stopping) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stopping.requested:
        time.sleep(min(POLL, max(0.0, deadline - time.monotonic())))


def _breathe(
    bus: STS3215Bus,
    axes: dict[int, Axis],
    resting: dict[int, int],
    seconds: float,
    stopping: Stopping,
) -> None:
    """Hold a pose, drifting a few ticks now and then so it does not look frozen."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stopping.requested:
        _dwell(random.uniform(2.5, 5.0), stopping)
        if stopping.requested or time.monotonic() >= deadline:
            break
        drift = {
            servo_id: axes[servo_id].clamp(position + random.randint(-6, 6))
            for servo_id, position in resting.items()
        }
        _travel(bus, axes, drift, 90, stopping, acc=10, timeout=1.5)


@dataclass(frozen=True)
class Step:
    """One leg of a behaviour: where to go, how briskly, and how long to hold."""

    goals: dict[int, int]
    speed: int
    acc: int
    dwell: float
    alive: bool = False


def _glance(yaw: Axis, pitch: Axis) -> list[Step]:
    """Look somewhere else, briskly, and hold it. One command."""
    return [
        Step(
            {
                yaw.servo_id: yaw.sample(0.3, floor=0.12),
                pitch.servo_id: pitch.sample(0.28, floor=0.14),
            },
            random.randint(520, 780),
            45,
            random.uniform(2.2, 5.0),
            True,
        )
    ]


def _look(yaw: Axis, pitch: Axis) -> list[Step]:
    """Something caught its attention: turn to it quickly and stay there."""
    return [
        Step(
            {
                yaw.servo_id: yaw.sample(0.62, floor=0.3),
                pitch.servo_id: pitch.sample(0.45, floor=0.2),
            },
            random.randint(900, 1250),
            75,
            random.uniform(1.6, 4.0),
            True,
        )
    ]


def _tilt(yaw: Axis, pitch: Axis) -> list[Step]:
    """The curious head-cock: turn, lift the chin, and hold it a good while."""
    side = random.choice((-1, 1))
    reach = (yaw.high - yaw.zero) if side > 0 else (yaw.zero - yaw.low)
    return [
        Step(
            {
                yaw.servo_id: yaw.clamp(
                    yaw.zero + side * round(reach * random.uniform(0.18, 0.42))
                ),
                pitch.servo_id: pitch.sample(0.4, floor=0.25),
            },
            random.randint(380, 560),
            30,
            random.uniform(3.5, 8.0),
            True,
        )
    ]


def _nod(yaw: Axis, pitch: Axis) -> list[Step]:
    """A single decisive dip of the chin, then back. Three commands."""
    down = pitch.clamp(pitch.zero - round((pitch.zero - pitch.low) * 0.7))
    up = pitch.clamp(pitch.zero + round((pitch.high - pitch.zero) * 0.3))
    return [
        Step({pitch.servo_id: down}, 1100, 90, 0.14),
        Step({pitch.servo_id: up}, 1100, 90, 0.14),
        Step(
            {pitch.servo_id: pitch.sample(0.2, floor=0.1)},
            600,
            45,
            random.uniform(2.0, 4.5),
            True,
        ),
    ]


def _rest(yaw: Axis, pitch: Axis) -> list[Step]:
    """Settle off-centre and stay there. Never square on."""
    return [
        Step(
            {
                yaw.servo_id: yaw.sample(0.18, floor=0.08),
                pitch.servo_id: pitch.sample(0.22, floor=0.12),
            },
            random.randint(300, 460),
            25,
            random.uniform(5.0, 11.0),
            True,
        )
    ]


# Nodding is punctuation, not the main event. There is deliberately no
# horizontal sweep: panning across at a fixed pitch reads as surveillance,
# and every behaviour moves pitch whenever it moves yaw.
BEHAVIOURS = (
    (_glance, 32),
    (_look, 26),
    (_tilt, 22),
    (_rest, 12),
    (_nod, 8),
)


def _choose(previous):
    """Pick the next behaviour, avoiding an immediate repeat."""
    options = [(fn, weight) for fn, weight in BEHAVIOURS if fn is not previous]
    functions = [fn for fn, _ in options]
    weights = [weight for _, weight in options]
    return random.choices(functions, weights=weights, k=1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-z", "--zeros", default="servo_zeros.json")
    parser.add_argument("--yaw-id", type=int, default=1)
    parser.add_argument("--pitch-id", type=int, default=2)
    parser.add_argument(
        "--margin",
        type=float,
        default=0.08,
        help="Fraction of travel kept unused at each end, as a safety inset.",
    )
    parser.add_argument(
        "--seconds", type=float, default=0.0, help="Run time. 0 runs until stopped."
    )
    parser.add_argument("--seed", type=int, help="Repeat a particular sequence.")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the hardware limit check. Not advised.",
    )
    parser.add_argument(
        "--keep-torque",
        action="store_true",
        dest="hold_torque",
        help="Stay energised on exit instead of going limp.",
    )
    args = parser.parse_args()
    if not 0.0 <= args.margin < 0.5:
        raise SystemExit("--margin must be 0.0-0.5")
    if args.seed is not None:
        random.seed(args.seed)

    zeros = load_zeros(args.zeros)
    for servo_id in (args.yaw_id, args.pitch_id):
        if servo_id not in zeros:
            raise SystemExit(f"{args.zeros} has no entry for servo {servo_id}")

    yaw = Axis.build(args.yaw_id, zeros[args.yaw_id], args.margin)
    pitch = Axis.build(args.pitch_id, zeros[args.pitch_id], args.margin)
    axes = {yaw.servo_id: yaw, pitch.servo_id: pitch}

    for name, axis in (("yaw", yaw), ("pitch", pitch)):
        rng = zeros[axis.servo_id]
        print(
            f"{name} (servo {axis.servo_id}): calibrated {rng.min}-{rng.max}, "
            f"using {axis.low}-{axis.high} "
            f"({degrees_from_ticks(axis.high - axis.low):.1f} deg), zero {axis.zero}"
        )

    stopping = Stopping()
    release_ids = () if args.hold_torque else [yaw.servo_id, pitch.servo_id]
    with STS3215Bus(args.port, args.baudrate, release_ids=release_ids) as bus:
        if not args.no_verify:
            problems = []
            for axis in (yaw, pitch):
                rng = zeros[axis.servo_id]
                for problem in check(bus, axis.servo_id, rng.min, rng.max):
                    problems.append(f"servo {axis.servo_id}: {problem}")
            if problems:
                raise SystemExit(
                    "\n".join(
                        [
                            "",
                            "Hardware travel limits do not match the calibration:",
                            *(f"  {p}" for p in problems),
                            "",
                            "Run apply_limits first so the servos enforce their own",
                            "range, or pass --no-verify to move without that guard.",
                        ]
                    )
                )
            print("\nHardware limits verified.")

        print("Centring...\n")
        _travel(bus, axes, {yaw.servo_id: yaw.zero, pitch.servo_id: pitch.zero}, 350, stopping)

        deadline = time.monotonic() + args.seconds if args.seconds else None
        moves = 0
        previous = None
        resting = {yaw.servo_id: yaw.zero, pitch.servo_id: pitch.zero}
        while not stopping.requested:
            if deadline and time.monotonic() >= deadline:
                break
            behaviour = _choose(previous)
            previous = behaviour
            moves += 1
            for step in behaviour(yaw, pitch):
                if stopping.requested:
                    break
                _travel(bus, axes, step.goals, step.speed, stopping, acc=step.acc)
                resting.update(step.goals)
                if step.alive:
                    _breathe(bus, axes, dict(resting), step.dwell, stopping)
                else:
                    _dwell(step.dwell, stopping)

        print(f"\nStopping after {moves} behaviours. Returning to centre.")
        stopping.requested = False  # let the last move finish
        _travel(bus, axes, {yaw.servo_id: yaw.zero, pitch.servo_id: pitch.zero}, 300, stopping)


if __name__ == "__main__":
    main()
