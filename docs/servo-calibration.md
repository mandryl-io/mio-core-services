# Servo Calibration

Every tool here is a module under `mio_core_services.firmware`, run the same way:

```bash
uv run --frozen python -m mio_core_services.firmware.<tool> [options]
```

Defaults target the working link — `/dev/ttyAMA0` at 115200 — so `--port` and
`--baudrate` are only needed on other hardware. See
[waveshare-servo-hat.md](waveshare-servo-hat.md) for the link itself.

Over SSH, tools that read the arrow keys need a real terminal:

```bash
ssh -t mio@raspberrypi.local 'cd ~/mio-core-services-waveshare && \
  ~/.local/bin/uv run --frozen python -m mio_core_services.firmware.<tool>'
```

`uv` is not on `PATH` in a non-interactive shell, hence the absolute path.

## The tools

| Tool | TTY | What it does |
| --- | --- | --- |
| `scan_servos` | no | Lists every ID answering on the bus, with positions |
| `read_servo` | no | Reads one servo's position, `--diagnose` adds link facts |
| `encode_servo_id` | no | Writes a new ID to EEPROM |
| `move_servo` | no | Moves one servo to an absolute position |
| `set_zero` | no | Records the current position as that servo's zero |
| `calibrate_joint` | **yes** | Guided pass: hold other axes, centre, fit part, set zero and limits |
| `calibrate_range` | **yes** | Jog to each limit in turn, then sweep to verify |
| `check_limits` | **yes** | Rehearses saved limits; any key stops immediately |
| `zero_servos` | **yes** | Original combined zero + limits pass, rewrites the file |
| `sweep_servos` | no | Sweeps every servo in a zeros file through its range |
| `teleop_servo` / `system_teleop` | **yes** | Live arrow-key control |

`set_zero`, `calibrate_joint`, `calibrate_range`, and `check_limits` **merge** into
`servo_zeros.json`; `zero_servos` rewrites it wholesale, so it will drop servos
you are not currently calibrating.

## Calibrating a joint in one pass

`calibrate_joint` runs the whole sequence for one axis, holding the others
steady so the joint is calibrated in the pose it will actually rest in.

Head pitch, with the neck held at its zero and the up/down arrows driving it:

```bash
uv run --frozen python -m mio_core_services.firmware.calibrate_joint \
  --id 2 --keys up-down
```

It:

1. Drives every other servo in the file to its recorded zero and holds it
2. Swings the bare shaft to both extremes and returns to its electrical
   centre (2048), so you can see the centre really is halfway, then waits for
   **Enter** while you fit the part square to it. `--skip-prove` parks without
   the swing
3. Jogs to the joint's **true centre** — Enter records it as the zero
4. Jogs to **maximum up**, Enter; returns to centre
5. Jogs to **maximum down**, Enter
6. Sweeps three times, pausing a second at each stop
7. Merges zero/min/max into `servo_zeros.json`

`--keys left-right` for a yaw axis, `--hold 1` to name which servos to hold
explicitly, `--centre` to park somewhere other than 2048. `q` aborts at any
point without writing.

### Jogging smoothly

Jogging re-issues the goal every 20 ms. If the servo is commanded much faster
than the goal actually advances, it sprints to each one, stops, and waits —
50 times a second, which feels like jitter and is worst on a loaded axis.

Every jogging tool therefore derives its tracking speed from the jog rate,
`step / 0.02` plus a little headroom, rather than using a fixed value. The
shared helper is `firmware/jog.py`; `zero_servos`, `teleop_servo` and
`system_teleop` previously paired step 5 with a fixed speed of 2400, roughly
ten times the rate the goal actually moved. Changing `--step` changes it
to match, so smaller steps stay smooth:

| `--step` | ticks/s | commanded speed |
| --- | --- | --- |
| 2 | 100 | 125 |
| 4 (default) | 200 | 250 |
| 8 | 400 | 500 |

If it still feels lumpy, drop `--step 2` for finer motion, or `--jog-acc 20`
for gentler ramps — too low and it visibly lags the keys. `--jog-speed`
overrides the automatic value, and `--travel-speed` controls the proving swing
and the returns to centre, which are not jogged and stay fast.

Limits are sorted, so it does not matter which key drives which way, and the
zero must fall between them or it refuses to save.

## Calibrating a joint step by step

The order matters: the zero is set with the part physically fitted, and the
limits are measured from that zero.

### 1. Confirm the servo is on the bus

```bash
uv run --frozen python -m mio_core_services.firmware.scan_servos
```

Never assume an ID. A silent read on `--id 1` usually means the servo is on a
different ID, not that the link is broken.

### 2. Centre the shaft before fitting the part

Fit the horn with the servo at its electrical centre (2048) so travel is
symmetric. Move it there, leaving torque on so it cannot drift while you work:

```bash
uv run --frozen python -m mio_core_services.firmware.move_servo --id 1 --position 2048
```

### 3. Record the zero

With the part fitted and the joint at its true rest position, store it:

```bash
uv run --frozen python -m mio_core_services.firmware.set_zero --id 1
```

This is the mechanism's zero, not the servo's. It will not usually be 2048 —
the difference is the mounting offset, and recording it is the whole point.

Pass `--position` to store a specific value, or `--release` to drop torque
afterwards.

### 4. Set the travel limits

```bash
uv run --frozen python -m mio_core_services.firmware.calibrate_range --id 1
```

Centres, asks you to jog to one limit and press Enter, returns to centre, asks
for the other, then sweeps three times pausing a second at each stop. `q`
aborts without writing.

Limits are sorted, so it does not matter which way the arrow keys drive the
joint. The zero must fall between them or it refuses to save.

Useful flags: `--step 2` for finer jogging, `--speed 150` for a slower sweep.

### 5. Rehearse the limits

```bash
uv run --frozen python -m mio_core_services.firmware.check_limits --speed 120 --cycles 1
```

**Any key stops every servo where it stands**, checked continuously during
travel rather than only at waypoints. Torque stays on so nothing drops.

With no `--cycles` it loops until stopped. Start slow and single-cycle on a
newly assembled mechanism, with a hand near the keyboard.

### 6. Release torque

```bash
uv run --frozen python -c "
from mio_core_services.firmware.sts3215 import STS3215Bus
with STS3215Bus() as b:
    b.enable_torque(1, False); b.enable_torque(2, False)"
```

Torque stays engaged after an abort or a jog, by design, so a joint cannot drop
under gravity mid-calibration.

## servo_zeros.json

```json
{
  "1": { "zero": 1659, "min": 1059, "max": 2259 },
  "2": { "zero": 3114, "min": 2600, "max": 3600 }
}
```

Positions are encoder ticks: 4096 per revolution, so **11.38 ticks per degree**
and 2048 is the electrical centre. `min` and `max` are absolute positions, not
offsets, and must bracket `zero`.

The file is machine-specific — it describes one physical build. Commit it if
there is only one robot; keep it out of the repo if there are several.

## Notes

- **Torque is left on** after jogging, aborting, or a centring move. That is
  deliberate. Release it explicitly when you are done.
- **`sweep_servos` drives to the recorded limits**, so bad limits are a
  collision. Prove them with `check_limits` first.
- **Two servos on ID 1 cannot share a bus** — both answer every packet.
  Separate them with `encode_servo_id` before chaining.
