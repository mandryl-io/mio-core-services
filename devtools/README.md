# Firmware lab (experimental)

A small local web app that turns the CLIs under
`mio_core_services/firmware/` into clickable workflows: first contact with
the bus, assigning IDs, **zeroing the servos**, calibrating a joint, writing
EEPROM limits, idle motion, and jitter tuning.

It does not reimplement the scripts. Each step builds the same
`uv run --frozen python -m …` command the docs already use.

## Run

From the repo root, on the machine that has the servo bus (or any machine if
you only want the commands):

```bash
make run-firmware-lab
# or
uv run --frozen python -m devtools.firmware_lab
```

Then open http://127.0.0.1:8765/

Shared fields at the top (port, baud, zeros file) apply to every step.
Workflow fields (servo ID, key mode, run duration, …) fill into the matching
flags.

## What the browser will and will not run

| Kind | In the lab |
| --- | --- |
| Scan, read, move, set_zero, apply_limits, sweep, idle_motion, monitor, jitter_test, tune | **Run this step** launches the real module in the repo root |
| Arrow-key / TTY tools (`zero_servos`, `calibrate_joint`, `calibrate_range`, `check_limits`, teleop) | Command only — paste into a real terminal (`ssh -t`) |

Moves that change hardware are labelled. TTY tools refuse to start from the
HTTP handler even if you call `/api/run`.

## Workflows

- **First contact with the bus** — `scan_servos` → `read_servo` → `move_servo`
- **Give a servo a unique ID** — `encode_servo_id` (one servo on the wire)
- **Zero the servos** — combined `zero_servos 1 2` pass (rewrites `servo_zeros.json`)
- **Calibrate one joint in a single pass** — `calibrate_joint`
- **Calibrate a joint step by step** — centre, `set_zero`, range, rehearse, EEPROM
- **Rehearse limits, then lock them in**
- **Drive both axes by hand** — `system_teleop`
- **Bring up idle motion**
- **Measure and tune jitter**

The scripts themselves still live in `mio_core_services/firmware/`. See
[docs/servo-calibration.md](../docs/servo-calibration.md).
