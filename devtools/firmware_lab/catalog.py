"""Catalog of firmware CLIs and the workflows that sequence them."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mio_core_services.firmware.runtime.sts3215 import (
    CENTER_POSITION,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
)

ZEROS_FILE = "servo_zeros.json"


@dataclass(frozen=True)
class Flag:
    key: str
    flag: str | None
    kind: str = "str"
    default: Any = None
    help: str = ""
    required: bool = False
    repeatable: bool = False
    choices: tuple[str, ...] | None = None
    omit_if_empty: bool = True


@dataclass(frozen=True)
class Tool:
    id: str
    module: str
    title: str
    group: str
    summary: str
    needs_tty: bool
    moves_hardware: bool
    flags: tuple[Flag, ...]
    notes: str = ""


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    tool: str
    body: str
    defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    summary: str
    when: str
    caution: str
    steps: tuple[Step, ...]
    params: tuple[Flag, ...] = ()


PORT = Flag(
    "port",
    "--port",
    default=DEFAULT_PORT,
    help="UART device. On a Pi 5 with the Waveshare HAT this is /dev/ttyAMA0.",
)
BAUD = Flag(
    "baudrate",
    "--baudrate",
    kind="int",
    default=DEFAULT_BAUDRATE,
    help="Bus baud rate. The HAT transparent-transmission firmware uses 115200.",
)
SERVO_ID = Flag("id", "--id", kind="int", default=1, help="Servo ID on the bus.")
OUTPUT_ZEROS = Flag(
    "zeros",
    "-o",
    default=ZEROS_FILE,
    help="JSON file of zeros and limits. Merged into, not rewritten wholesale.",
)
INPUT_ZEROS = Flag(
    "zeros",
    "-z",
    default=ZEROS_FILE,
    help="JSON file of zeros and limits to read.",
)
TELEOP_ZEROS = Flag(
    "zeros",
    "--zeros",
    default=ZEROS_FILE,
    help="JSON file of zeros and limits.",
)
KEEP_TORQUE = Flag(
    "keep_torque",
    "--keep-torque",
    kind="bool",
    default=False,
    help="Leave torque on when the tool exits, instead of going limp.",
)


TOOLS: tuple[Tool, ...] = (
    Tool(
        id="scan_servos",
        module="mio_core_services.firmware.setup.scan_servos",
        title="Scan the bus",
        group="setup",
        summary="List every ID that answers, with its current position.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            PORT,
            BAUD,
            Flag(
                "max_id",
                "--max-id",
                kind="int",
                default=253,
                help="Highest ID to probe. Lower this for a faster sweep.",
            ),
        ),
        notes="Never assume an ID. A silent read usually means a different ID, not a dead link.",
    ),
    Tool(
        id="read_servo",
        module="mio_core_services.firmware.setup.read_servo",
        title="Read one servo",
        group="setup",
        summary="Read one servo's position. --diagnose adds UART preflight facts.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            PORT,
            BAUD,
            SERVO_ID,
            Flag(
                "diagnose",
                "--diagnose",
                kind="bool",
                default=False,
                help="Print UART preflight details even when the servo replies.",
            ),
        ),
    ),
    Tool(
        id="encode_servo_id",
        module="mio_core_services.firmware.setup.encode_servo_id",
        title="Assign a servo ID",
        group="setup",
        summary="Write a new ID to EEPROM. Connect only that servo to the bus.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            PORT,
            BAUD,
            Flag("new_id", "--new-id", kind="int", required=True, help="ID to write."),
            Flag(
                "current_id",
                "--current-id",
                kind="int",
                default=254,
                help="Current ID. Default 254 (broadcast) — only one servo on the bus.",
            ),
        ),
        notes="Two servos on ID 1 cannot share a bus. Separate them before chaining.",
    ),
    Tool(
        id="move_servo",
        module="mio_core_services.firmware.setup.move_servo",
        title="Move one servo",
        group="setup",
        summary="One-shot move of a single servo, to confirm the bus is alive.",
        needs_tty=False,
        moves_hardware=True,
        flags=(
            PORT,
            BAUD,
            SERVO_ID,
            Flag(
                "position",
                "--position",
                kind="int",
                default=CENTER_POSITION,
                help="Goal position 0–4095. 2048 is the electrical centre.",
            ),
        ),
        notes="Use 2048 to centre a shaft before fitting a horn.",
    ),
    Tool(
        id="move_system",
        module="mio_core_services.firmware.setup.move_system",
        title="Move both axes",
        group="setup",
        summary="One-shot move of servos 1 and 2 together.",
        needs_tty=False,
        moves_hardware=True,
        flags=(
            PORT,
            BAUD,
            Flag(
                "position_1",
                "--position-1",
                kind="int",
                default=CENTER_POSITION,
                help="Goal for servo 1 (yaw / neck).",
            ),
            Flag(
                "position_2",
                "--position-2",
                kind="int",
                default=CENTER_POSITION,
                help="Goal for servo 2 (pitch / head).",
            ),
        ),
    ),
    Tool(
        id="set_zero",
        module="mio_core_services.firmware.calibration.set_zero",
        title="Record a zero",
        group="calibration",
        summary="Store the current position (or --position) as that servo's zero.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            SERVO_ID,
            PORT,
            BAUD,
            OUTPUT_ZEROS,
            Flag(
                "position",
                "--position",
                kind="int",
                help="Record this instead of reading the servo.",
            ),
            Flag(
                "release",
                "--release",
                kind="bool",
                default=False,
                help="Drop torque after saving.",
            ),
        ),
        notes="This is the mechanism's zero, not the servo's electrical centre.",
    ),
    Tool(
        id="zero_servos",
        module="mio_core_services.firmware.calibration.zero_servos",
        title="Zero servos (combined pass)",
        group="calibration",
        summary="Jog each ID to its physical zero, then type ± travel. Rewrites the JSON file.",
        needs_tty=True,
        moves_hardware=True,
        flags=(
            Flag(
                "ids",
                None,
                default="1 2",
                required=True,
                help="Servo IDs to zero, in order, separated by spaces.",
            ),
            PORT,
            BAUD,
            OUTPUT_ZEROS,
            Flag("step", "--step", kind="int", default=5, help="Ticks per jog tick."),
            Flag("speed", "--speed", kind="int", help="Tracking speed. Blank matches the jog rate."),
            KEEP_TORQUE,
        ),
        notes="Rewrites servo_zeros.json wholesale, so it drops servos you are not calibrating.",
    ),
    Tool(
        id="calibrate_joint",
        module="mio_core_services.firmware.calibration.calibrate_joint",
        title="Calibrate a joint",
        group="calibration",
        summary="Guided pass: hold other axes, centre, fit the part, set zero and limits.",
        needs_tty=True,
        moves_hardware=True,
        flags=(
            Flag("id", "--id", kind="int", required=True, help="Joint to calibrate."),
            Flag(
                "keys",
                "--keys",
                kind="choice",
                default="left-right",
                choices=("left-right", "up-down"),
                help="Which arrow keys jog this joint.",
            ),
            Flag(
                "hold",
                "--hold",
                repeatable=True,
                help="Servo to hold at its recorded zero. Repeatable. Blank = every other ID in the file.",
            ),
            PORT,
            BAUD,
            OUTPUT_ZEROS,
            Flag(
                "centre",
                "--centre",
                kind="int",
                default=CENTER_POSITION,
                help="Where to park the shaft while the part is fitted.",
            ),
            Flag(
                "skip_prove",
                "--skip-prove",
                kind="bool",
                default=False,
                help="Park at centre without the full-travel swing first.",
            ),
            Flag("step", "--step", kind="int", default=4, help="Ticks per jog tick."),
            Flag("jog_speed", "--jog-speed", kind="int", help="Tracking speed while jogging."),
            Flag("jog_acc", "--jog-acc", kind="int", default=40, help="Jog acceleration."),
            Flag(
                "travel_speed",
                "--travel-speed",
                kind="int",
                default=800,
                help="Speed for the proving swing and returns to centre.",
            ),
            Flag("speed", "--speed", kind="int", default=300, help="Sweep speed."),
            Flag("cycles", "--cycles", kind="int", default=3, help="Verification sweeps."),
            KEEP_TORQUE,
        ),
        notes="q aborts without writing. Over SSH this needs ssh -t.",
    ),
    Tool(
        id="calibrate_range",
        module="mio_core_services.firmware.calibration.calibrate_range",
        title="Set travel limits",
        group="calibration",
        summary="Jog to each limit in turn, then sweep to verify. Merges into the zeros file.",
        needs_tty=True,
        moves_hardware=True,
        flags=(
            SERVO_ID,
            PORT,
            BAUD,
            OUTPUT_ZEROS,
            Flag("zero", "--zero", kind="int", help="Centre. Defaults to the value in the file."),
            Flag("step", "--step", kind="int", default=4, help="Ticks per jog tick."),
            Flag("jog_speed", "--jog-speed", kind="int"),
            Flag("jog_acc", "--jog-acc", kind="int", default=40),
            Flag("speed", "--speed", kind="int", default=300, help="Sweep speed."),
            Flag("cycles", "--cycles", kind="int", default=3),
            KEEP_TORQUE,
        ),
    ),
    Tool(
        id="check_limits",
        module="mio_core_services.firmware.calibration.check_limits",
        title="Rehearse limits",
        group="calibration",
        summary="Sweeps saved limits. Any key stops every servo where it stands.",
        needs_tty=True,
        moves_hardware=True,
        flags=(
            Flag(
                "ids",
                "--id",
                repeatable=True,
                help="Servo to test. Repeatable. Blank = every servo in the file.",
            ),
            PORT,
            BAUD,
            INPUT_ZEROS,
            Flag("speed", "--speed", kind="int", default=300, help="Lower is slower."),
            Flag("pause", "--pause", kind="float", default=1.0, help="Seconds at each stop."),
            Flag(
                "cycles",
                "--cycles",
                kind="int",
                default=0,
                help="Sweeps per servo. 0 repeats until a key is pressed.",
            ),
            Flag("timeout", "--timeout", kind="float", default=20.0),
            KEEP_TORQUE,
        ),
        notes="Start slow and single-cycle on a newly assembled mechanism.",
    ),
    Tool(
        id="apply_limits",
        module="mio_core_services.firmware.calibration.apply_limits",
        title="Write EEPROM limits",
        group="calibration",
        summary="Write calibrated min/max into each servo, or only verify them.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            PORT,
            BAUD,
            INPUT_ZEROS,
            Flag(
                "ids",
                "--id",
                repeatable=True,
                help="Servo to write. Repeatable. Blank = every servo in the file.",
            ),
            Flag(
                "verify",
                "--verify",
                kind="bool",
                default=False,
                help="Only report; change nothing.",
            ),
            Flag(
                "factory",
                "--factory",
                kind="bool",
                default=False,
                help="Restore full 0–4095 travel instead.",
            ),
        ),
        notes="EEPROM writes persist across power cycles. Use --verify first.",
    ),
    Tool(
        id="sweep_servos",
        module="mio_core_services.firmware.calibration.sweep_servos",
        title="Sweep recorded ranges",
        group="calibration",
        summary="Drives every servo in the zeros file min→max→zero.",
        needs_tty=False,
        moves_hardware=True,
        flags=(
            Flag(
                "zeros_positional",
                None,
                default=ZEROS_FILE,
                required=True,
                help="JSON file of id → zero/min/max.",
            ),
            PORT,
            BAUD,
            Flag("speed", "--speed", kind="int", default=1000),
            Flag("timeout", "--timeout", kind="float", default=10.0),
            Flag("hold", "--hold", kind="float", default=0.4, help="Pause at min, max, and zero."),
            KEEP_TORQUE,
        ),
        notes="Bad limits are a collision. Prove them with check_limits first.",
    ),
    Tool(
        id="teleop_servo",
        module="mio_core_services.firmware.calibration.teleop_servo",
        title="Teleop one servo",
        group="calibration",
        summary="Live arrow-key control of one servo.",
        needs_tty=True,
        moves_hardware=True,
        flags=(
            PORT,
            BAUD,
            SERVO_ID,
            Flag("zeros", "--zeros", help="Reset this ID to its recorded position before teleop."),
            Flag("speed", "--speed", kind="int", default=900, help="Jog velocity in ticks/s."),
            Flag("acc", "--acc", kind="int", default=60),
            Flag("stiff", "--stiff", kind="bool", default=False, help="Keep torque on while stopped."),
            Flag("limp_after", "--limp-after", kind="float", default=0.4),
            Flag("invert_x", "--invert-x", kind="bool", default=False),
            KEEP_TORQUE,
        ),
    ),
    Tool(
        id="system_teleop",
        module="mio_core_services.firmware.calibration.system_teleop",
        title="Teleop both axes",
        group="calibration",
        summary="Live control of yaw and pitch, clamped to saved limits.",
        needs_tty=True,
        moves_hardware=True,
        flags=(
            PORT,
            BAUD,
            Flag("id_1", "--id-1", kind="int", default=1, help="Left/right (yaw / neck)."),
            Flag("id_2", "--id-2", kind="int", default=2, help="Up/down (pitch / head)."),
            TELEOP_ZEROS,
            Flag(
                "free",
                "--free",
                kind="bool",
                default=False,
                help="Ignore the zeros file and allow full 0–4095 travel.",
            ),
            Flag("speed", "--speed", kind="int", default=900),
            Flag("acc", "--acc", kind="int", default=60),
            Flag("stiff", "--stiff", kind="bool", default=False),
            Flag("limp_after", "--limp-after", kind="float", default=0.4),
            Flag("invert_x", "--invert-x", kind="bool", default=False),
            KEEP_TORQUE,
        ),
        notes="Safest way to exercise the mechanism. --free drops the clamps.",
    ),
    Tool(
        id="idle_motion",
        module="mio_core_services.firmware.runtime.idle_motion",
        title="Idle motion",
        group="runtime",
        summary="Natural head movement inside the calibrated range.",
        needs_tty=False,
        moves_hardware=True,
        flags=(
            PORT,
            BAUD,
            INPUT_ZEROS,
            Flag("yaw_id", "--yaw-id", kind="int", default=1),
            Flag("pitch_id", "--pitch-id", kind="int", default=2),
            Flag("margin", "--margin", kind="float", default=0.08),
            Flag(
                "seconds",
                "--seconds",
                kind="float",
                default=0.0,
                help="Run time. 0 runs until stopped — set a bound from this lab.",
            ),
            Flag("seed", "--seed", kind="int"),
            Flag("no_verify", "--no-verify", kind="bool", default=False),
            Flag("no_intro", "--no-intro", kind="bool", default=False),
            Flag("centre_speed", "--centre-speed", kind="int", default=70),
            Flag("sweep_speed", "--sweep-speed", kind="int", default=400),
            Flag("stiff", "--stiff", kind="bool", default=False),
            KEEP_TORQUE,
        ),
        notes="Refuses to start unless EEPROM limits match the calibration, unless --no-verify.",
    ),
    Tool(
        id="monitor_servo",
        module="mio_core_services.firmware.tuning.monitor_servo",
        title="Monitor supply and load",
        group="tuning",
        summary="Sample voltage, load and temperature to catch supply sag.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            SERVO_ID,
            PORT,
            BAUD,
            Flag("seconds", "--seconds", kind="float", default=30.0),
            Flag("interval", "--interval", kind="float", default=0.1),
            Flag("csv", "--csv", help="Write every sample to this path."),
        ),
        notes="Jog the joint while it samples. More than about 1 V of sag is the supply, not the PID.",
    ),
    Tool(
        id="jitter_test",
        module="mio_core_services.firmware.tuning.jitter_test",
        title="Measure hold jitter",
        group="tuning",
        summary="Hold a position with torque on, then off, and report peak-to-peak movement.",
        needs_tty=False,
        moves_hardware=True,
        flags=(
            SERVO_ID,
            PORT,
            BAUD,
            INPUT_ZEROS,
            Flag("seconds", "--seconds", kind="float", default=6.0),
            Flag("settle_timeout", "--settle-timeout", kind="float", default=20.0),
            Flag("at", "--at", kind="int", help="Hold this position. Blank = recorded zero."),
        ),
    ),
    Tool(
        id="tune_servo",
        module="mio_core_services.firmware.tuning.tune_servo",
        title="Tune the position loop",
        group="tuning",
        summary="Read or set the EEPROM registers that cause stationary hunting.",
        needs_tty=False,
        moves_hardware=False,
        flags=(
            SERVO_ID,
            PORT,
            BAUD,
            Flag("p", "--p", kind="int"),
            Flag("i", "--i", kind="int"),
            Flag("d", "--d", kind="int"),
            Flag("punch", "--punch", kind="int"),
            Flag("cw_dead_zone", "--cw-dead-zone", kind="int"),
            Flag("ccw_dead_zone", "--ccw-dead-zone", kind="int"),
            Flag("dead_zone", "--dead-zone", kind="int", help="Set both dead zones at once."),
            Flag(
                "baseline",
                "--baseline",
                kind="bool",
                default=False,
                help="Restore P 32, I 0, D 32, punch 16, dead zone 1.",
            ),
            Flag(
                "factory",
                "--factory",
                kind="bool",
                default=False,
                help="Restore manufacturer defaults for every register this tool knows.",
            ),
        ),
        notes="EEPROM writes persist. Leave I at 0. With no write flags this only prints current values.",
    ),
)


WORKFLOWS: tuple[Workflow, ...] = (
    Workflow(
        id="first-contact",
        title="First contact with the bus",
        summary="Confirm the HAT, UART, and servos before moving anything calibrated.",
        when="A factory-fresh HAT, a new Pi image, or a bus that has gone silent.",
        caution="Scan before you assume IDs. Moving a servo whose ID you guessed can hit a stop.",
        params=(
            Flag("id", None, kind="int", default=1, help="Servo to read and optionally move."),
            Flag(
                "max_id",
                None,
                kind="int",
                default=10,
                help="Highest ID to scan. Raise toward 253 if a servo is missing.",
            ),
            Flag(
                "position",
                None,
                kind="int",
                default=CENTER_POSITION,
                help="One-shot move target after the read. 2048 centres the shaft.",
            ),
        ),
        steps=(
            Step(
                id="scan",
                title="See who is on the bus",
                tool="scan_servos",
                body="Lists every ID that answers. If nothing replies, check bus power and the HAT firmware — not the calibration file.",
                defaults={"max_id": 10},
            ),
            Step(
                id="read",
                title="Read one servo",
                tool="read_servo",
                body="Confirm that ID with --diagnose so UART preflight facts are in the log.",
                defaults={"diagnose": True},
            ),
            Step(
                id="nudge",
                title="Nudge it once",
                tool="move_servo",
                body="A single move to the electrical centre (or the position you set). This is the cheapest proof the bus can write as well as read.",
            ),
        ),
    ),
    Workflow(
        id="assign-ids",
        title="Give a servo a unique ID",
        summary="Write EEPROM so two factory-default servos can share the bus.",
        when="A new STS3215 still on ID 1, or two servos answering the same packet.",
        caution="Connect only the servo you are encoding. Broadcast writes hit every ID on the wire.",
        params=(
            Flag("new_id", None, kind="int", required=True, help="ID to assign (1 = neck, 2 = head)."),
            Flag(
                "current_id",
                None,
                kind="int",
                default=254,
                help="Current ID. 254 broadcasts — only one servo on the bus.",
            ),
        ),
        steps=(
            Step(
                id="encode",
                title="Write the new ID",
                tool="encode_servo_id",
                body="Only the target servo should be plugged in. Default current ID 254 is broadcast.",
            ),
            Step(
                id="scan",
                title="Confirm it answers",
                tool="scan_servos",
                body="The new ID should appear and the old one should not.",
                defaults={"max_id": 10},
            ),
        ),
    ),
    Workflow(
        id="zero-servos",
        title="Zero the servos",
        summary="The original combined pass: jog each ID to its physical rest, then type ± travel.",
        when="You want one sitting to record zeros and limits for the neck and head together.",
        caution="This rewrites servo_zeros.json. Servos you do not list are dropped from the file.",
        params=(
            Flag(
                "ids",
                None,
                default="1 2",
                help="IDs to zero, in order. Neck then head is 1 2.",
            ),
            Flag("step", None, kind="int", default=5, help="Ticks per jog tick. Drop to 2 if it feels lumpy."),
        ),
        steps=(
            Step(
                id="scan",
                title="Confirm both IDs",
                tool="scan_servos",
                body="Do not start the combined pass until both IDs answer.",
                defaults={"max_id": 10},
            ),
            Step(
                id="zero",
                title="Jog to zero and type travel",
                tool="zero_servos",
                body="Needs a keyboard TTY (ssh -t). Arrow keys jog, Enter records the zero, then type ± travel in ticks (300 or +400/-200). q aborts.",
            ),
        ),
    ),
    Workflow(
        id="calibrate-joint",
        title="Calibrate one joint in a single pass",
        summary="Hold the other axis, centre the shaft, fit the part, then record zero and limits.",
        when="A joint is assembled and you want the guided calibrate_joint sequence.",
        caution="Torque stays useful while you fit the part — pass --keep-torque if the joint cannot support itself.",
        params=(
            Flag("id", None, kind="int", required=True, default=2, help="Joint to calibrate. 1 = yaw, 2 = pitch."),
            Flag(
                "keys",
                None,
                kind="choice",
                default="up-down",
                choices=("left-right", "up-down"),
                help="left-right for yaw, up-down for pitch.",
            ),
            Flag(
                "keep_torque",
                None,
                kind="bool",
                default=False,
                help="Leave torque on when the tool exits.",
            ),
        ),
        steps=(
            Step(
                id="calibrate",
                title="Run the guided pass",
                tool="calibrate_joint",
                body="Holds every other servo in the file at its recorded zero. Swing, fit, jog to true centre, then both limits. Merges into the zeros file. Needs ssh -t.",
            ),
        ),
    ),
    Workflow(
        id="calibrate-step-by-step",
        title="Calibrate a joint step by step",
        summary="Centre the shaft, record the zero with the part fitted, then measure limits separately.",
        when="You want each firmware script on its own, in the order the calibration doc describes.",
        caution="The zero is set with the part physically fitted. Limits are measured from that zero.",
        params=(
            Flag("id", None, kind="int", default=1, help="Joint to work on."),
            Flag("step", None, kind="int", default=4, help="Jog step for the limits pass."),
        ),
        steps=(
            Step(
                id="scan",
                title="Confirm the servo is on the bus",
                tool="scan_servos",
                body="Never assume an ID.",
                defaults={"max_id": 10},
            ),
            Step(
                id="centre",
                title="Centre the shaft before fitting the part",
                tool="move_servo",
                body="Fit the horn at 2048 so travel is symmetric. Torque stays on after the move so the shaft cannot drift while you work.",
                defaults={"position": CENTER_POSITION},
            ),
            Step(
                id="zero",
                title="Record the mechanism zero",
                tool="set_zero",
                body="With the part fitted and the joint at its true rest, store the current position. It will not usually be 2048.",
            ),
            Step(
                id="range",
                title="Jog the travel limits",
                tool="calibrate_range",
                body="Needs a TTY. Centres, asks for each limit, then sweeps. Limits are sorted, so key direction does not matter.",
            ),
            Step(
                id="rehearse",
                title="Rehearse slowly",
                tool="check_limits",
                body="Any key stops where it stands. Start with one slow cycle.",
                defaults={"cycles": 1, "speed": 120},
            ),
            Step(
                id="apply",
                title="Write the limits into EEPROM",
                tool="apply_limits",
                body="Python clamping only protects code that clamps. The servo will also enforce EEPROM min/max itself.",
            ),
        ),
    ),
    Workflow(
        id="rehearse-and-apply",
        title="Rehearse limits, then lock them in",
        summary="Prove servo_zeros.json on the mechanism, then write EEPROM (or only verify).",
        when="Zeros and limits are already in the file and you want them on the servos.",
        caution="sweep_servos drives to the recorded limits. Prove with check_limits first.",
        params=(
            Flag("cycles", None, kind="int", default=1, help="Rehearsal sweeps per servo."),
            Flag("speed", None, kind="int", default=120, help="Rehearsal speed. Lower is slower."),
        ),
        steps=(
            Step(
                id="rehearse",
                title="Rehearse with a hand near the keyboard",
                tool="check_limits",
                body="TTY required. Any key stops every servo immediately.",
            ),
            Step(
                id="verify",
                title="Read EEPROM without writing",
                tool="apply_limits",
                body="Confirm what is already in the servos before changing it.",
                defaults={"verify": True},
            ),
            Step(
                id="write",
                title="Write calibrated min/max",
                tool="apply_limits",
                body="Writes each servo's calibrated range and reads it back.",
                defaults={"verify": False},
            ),
        ),
    ),
    Workflow(
        id="drive-both-axes",
        title="Drive both axes by hand",
        summary="Live teleop clamped to the calibrated range — the safest way to watch for jitter.",
        when="You want to exercise the head without writing calibration.",
        caution="--free ignores the zeros file and allows the full 0–4095 travel.",
        params=(
            Flag("speed", None, kind="int", default=900, help="Jog velocity in ticks/s."),
            Flag(
                "free",
                None,
                kind="bool",
                default=False,
                help="Ignore calibrated limits.",
            ),
        ),
        steps=(
            Step(
                id="teleop",
                title="System teleop",
                tool="system_teleop",
                body="Left/right (or a/d) is yaw, up/down (or w/s) is pitch. Starts at recorded zeros. Needs ssh -t.",
            ),
        ),
    ),
    Workflow(
        id="idle-motion",
        title="Bring up idle motion",
        summary="Verify EEPROM limits, then run the naturalistic head behaviours for a bounded time.",
        when="Calibration is written and you want the boot motion without systemd.",
        caution="Without --seconds this runs until stopped. The lab defaults to a 30 second preview.",
        params=(
            Flag("seconds", None, kind="float", default=30.0, help="Bound the run so the lab can return."),
            Flag("margin", None, kind="float", default=0.08, help="Unused travel at each end."),
        ),
        steps=(
            Step(
                id="verify",
                title="Confirm EEPROM matches the file",
                tool="apply_limits",
                body="idle_motion refuses to start unless this check would pass.",
                defaults={"verify": True},
            ),
            Step(
                id="idle",
                title="Run idle motion",
                tool="idle_motion",
                body="Glance, nod, rest, tilt, scan, perk. Returns to centre and goes limp on exit.",
                defaults={"seconds": 30.0},
            ),
        ),
    ),
    Workflow(
        id="debug-jitter",
        title="Measure and tune jitter",
        summary="Supply first, then hold-still measurement, then EEPROM position-loop registers.",
        when="A joint buzzes while holding, or stutters while travelling.",
        caution="Widening the dead zone or lowering punch usually makes hunting worse. Leave I at 0.",
        params=(
            Flag("id", None, kind="int", default=1, help="Servo that is misbehaving."),
            Flag("seconds", None, kind="float", default=10.0, help="How long to sample the supply."),
        ),
        steps=(
            Step(
                id="monitor",
                title="Watch the supply while you jog",
                tool="monitor_servo",
                body="More than about 1 V of sag is wiring or the PSU, not the position loop.",
                defaults={"seconds": 10.0},
            ),
            Step(
                id="measure",
                title="Measure hold jitter",
                tool="jitter_test",
                body="Under 3 ticks driven is encoder noise. Driven noisy / limp steady means tune the loop. Noisy both ways is mechanical.",
            ),
            Step(
                id="inspect",
                title="Read the current registers",
                tool="tune_servo",
                body="No write flags — print only.",
            ),
            Step(
                id="baseline",
                title="Restore the reviewed baseline",
                tool="tune_servo",
                body="P 32, I 0, D 32, punch 16, dead zone 1. Then raise --d from here, measuring after each change.",
                defaults={"baseline": True},
            ),
        ),
    ),
)


def get_tool(tool_id: str) -> Tool:
    for tool in TOOLS:
        if tool.id == tool_id:
            return tool
    raise KeyError(f"Unknown firmware tool: {tool_id}")


def get_workflow(workflow_id: str) -> Workflow:
    for workflow in WORKFLOWS:
        if workflow.id == workflow_id:
            return workflow
    raise KeyError(f"Unknown workflow: {workflow_id}")


def catalog_payload() -> dict[str, Any]:
    return {
        "shared": {
            "port": DEFAULT_PORT,
            "baudrate": DEFAULT_BAUDRATE,
            "zeros": ZEROS_FILE,
        },
        "tools": [asdict(tool) for tool in TOOLS],
        "workflows": [asdict(workflow) for workflow in WORKFLOWS],
    }
