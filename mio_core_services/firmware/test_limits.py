"""Exercise the saved travel limits. Any key stops the servo immediately."""

from __future__ import annotations

import argparse
import sys
import time

from mio_core_services.firmware.servo_zeros_io import degrees_from_ticks
from mio_core_services.firmware.sts3215 import (
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    STS3215Bus,
)
from mio_core_services.firmware.zero_servos import RawTerminal, load_zeros

ARRIVE_TOLERANCE = 20


class Aborted(Exception):
    """Raised as soon as the operator hits a key."""


def _check_abort(terminal: RawTerminal, timeout: float) -> None:
    if terminal.poll_key(timeout) is not None:
        raise Aborted


def _say(message: str = "") -> None:
    sys.stdout.write(f"{message}\r\n")
    sys.stdout.flush()


def _goto(
    bus: STS3215Bus,
    terminal: RawTerminal,
    servo_id: int,
    goal: int,
    label: str,
    timeout: float,
) -> None:
    """Drive to goal, watching for a keypress the whole way."""
    bus.set_goal(goal, servo_id=servo_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_abort(terminal, 0.05)
        if abs(bus.position(servo_id=servo_id) - goal) <= ARRIVE_TOLERANCE:
            break
    _say(f"  {label}: {goal} -> at {bus.position(servo_id=servo_id)}")


def _hold_here(bus: STS3215Bus, servo_id: int) -> int:
    """Freeze the servo at wherever it currently is."""
    position = bus.position(servo_id=servo_id)
    bus.set_goal(position, servo_id=servo_id)
    return position


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--id",
        type=int,
        action="append",
        dest="ids",
        help="Servo to test. Repeatable. Defaults to every servo in the file.",
    )
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("-z", "--zeros", default="servo_zeros.json")
    parser.add_argument(
        "--speed", type=int, default=300, help="Lower is slower."
    )
    parser.add_argument("--pause", type=float, default=1.0, help="Seconds at each stop.")
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Sweeps per servo. 0 repeats until a key is pressed.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    if args.pause < 0:
        raise SystemExit("--pause must be >= 0")
    if not sys.stdin.isatty():
        raise SystemExit("Need a TTY to watch for the abort key. Run with: ssh -t ...")

    zeros = load_zeros(args.zeros)
    ids = args.ids or sorted(zeros)
    missing = [servo_id for servo_id in ids if servo_id not in zeros]
    if missing:
        raise SystemExit(f"{args.zeros} has no entry for servo(s) {missing}")

    print(f"Testing limits from {args.zeros} at speed {args.speed}.")
    for servo_id in ids:
        rng = zeros[servo_id]
        print(
            f"  servo {servo_id}: {rng.min} - {rng.max}, centre {rng.zero} "
            f"({degrees_from_ticks(rng.zero - rng.min):.1f} deg / "
            f"{degrees_from_ticks(rng.max - rng.zero):.1f} deg)"
        )
    print("\nPress ANY KEY to stop immediately.\n")

    stopped_at: dict[int, int] = {}
    with STS3215Bus(args.port, args.baudrate) as bus:
        try:
            with RawTerminal() as terminal:
                for servo_id in ids:
                    rng = zeros[servo_id]
                    bus.prepare(servo_id=servo_id, speed=args.speed, acc=20)
                    _say(f"servo {servo_id}:")
                    _goto(bus, terminal, servo_id, rng.zero, "centre", args.timeout)
                    _check_abort(terminal, args.pause)

                    cycle = 0
                    while args.cycles == 0 or cycle < args.cycles:
                        cycle += 1
                        for label, goal in (
                            ("max", rng.max),
                            ("centre", rng.zero),
                            ("min", rng.min),
                            ("centre", rng.zero),
                        ):
                            _goto(
                                bus,
                                terminal,
                                servo_id,
                                goal,
                                f"cycle {cycle} {label}",
                                args.timeout,
                            )
                            _check_abort(terminal, args.pause)
                    _say()
        except Aborted:
            for servo_id in ids:
                try:
                    stopped_at[servo_id] = _hold_here(bus, servo_id)
                except TimeoutError:
                    pass
            _say()
            _say("STOPPED.")
            for servo_id, position in stopped_at.items():
                _say(f"  servo {servo_id} held at {position}")
            _say("Torque is still on. Release it with set_zero --release if needed.")
            raise SystemExit(130) from None

    print("Done. All limits reached without a stop.")


if __name__ == "__main__":
    main()
