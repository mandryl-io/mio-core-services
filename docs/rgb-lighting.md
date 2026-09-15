# Lighting

A WS2811 RGB light and two white eye LEDs, on one header.

## Wiring

| Signal | Pin | |
| --- | --- | --- |
| RGB 5V | 2 | 5V |
| RGB GND | 6 | ground |
| RGB DI | 12 | GPIO18, `board.D18` in software |
| Eye grounds | 14 | ground |
| Left eye | 16 | GPIO23 |
| Right eye | 18 | GPIO24 |

The RGB light and the eyes are separate programs on separate pins and can run
at the same time, alongside the head.

# The RGB light

The Pi drives DI at 3.3 V while a 5 V WS2811 may want a higher data-high
threshold. It usually works direct. Flicker, wrong colours or a dead strand
points at that margin first, and a 74AHCT125 level shifter on the data line
fixes it.

## Why not `rpi_ws281x`

The old bit-banged PWM/DMA route does not exist on the Pi 5 — the GPIO is
behind the RP1 southbridge, not on the SoC. Adafruit's Pi 5 library drives the
pixels from the RP1's PIO block through `/dev/pio0` instead, which is why that
device node has to exist before anything here runs.

## Setup, once, on the Pi

The LED stack wants system site packages, so it lives in its own virtualenv
rather than the repository's `.venv`. It is deliberately kept out of
`pyproject.toml`: adding it there would invalidate `uv.lock` and break the
`uv run --frozen` servo commands.

```bash
sudo apt update && sudo apt install -y python3-venv
python3 -m venv ~/ledenv --system-site-packages
~/ledenv/bin/pip install Adafruit-Blinka Adafruit-Blinka-Raspberry-Pi5-Neopixel \
  adafruit-circuitpython-pixelbuf
```

Confirm the PIO device is there:

```bash
ls -l /dev/pio0
```

No such file means the firmware is too old:

```bash
sudo apt update && sudo apt upgrade -y
sudo rpi-eeprom-update -a
sudo reboot
```

## Running it

From the repository root, so the package is importable:

```bash
cd ~/mio-core-services-waveshare
~/ledenv/bin/python -m mio_core_services.lighting.color_cycle
```

**Check the byte order first.** WS2811 breakouts do not agree on it, and a
wrong order silently swaps your colours:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.color_cycle --check-order
```

That names each colour before showing it. If the light disagrees with the
name, pass `--order RGB` or `--order BGR` — and if you settle on one, change
`DEFAULT_ORDER` in `mio_core_services/lighting/pixels.py` so you stop typing it.

## The sequence

One lap is ten colours: red, green, blue on their own, then red, orange,
yellow, green, blue, indigo, violet.

Brightness steps through a seven-level ladder that runs continuously across
laps rather than restarting. Ten colours against seven levels are coprime, so
the pairing shifts every lap and the full pattern takes 70 beats to come round
— each colour is seen at every brightness before anything repeats.

The RGB values are tuned by eye on a WS2811, not taken from sRGB names. An
additive LED's green channel dominates, so a literal orange or yellow washes
out and the two look identical; both are pulled well down to keep the seven
spectrum steps apart.

Brightness is gamma corrected before it is written. Perceived brightness goes
roughly as the 2.2 power of emitted light, so scaling raw channel values makes
a nominally dim LED look far brighter than asked — which is exactly what a
brightness ladder would otherwise show off. `--gamma 0` disables it.

## Options

| Flag | Default | |
| --- | --- | --- |
| `--check-order` | | Name and show red, green, blue, then exit |
| `--hold` | 1.5 | Seconds on each colour |
| `--fade` | 0.35 | Seconds crossing between colours; 0 snaps |
| `--laps` | 0 | Laps to run; 0 until stopped |
| `--levels` | | Override the ladder, e.g. `1,0.5,0.2` |
| `--max-brightness` | 1.0 | Ceiling on every level, for a dim room |
| `--gamma` | 2.2 | 0 disables the correction |
| `--pin` | `D18` | Blinka pin name |
| `-n`, `--count` | 1 | Pixels on the strand |
| `--order` | `GRB` | Pixel byte order |
| `--keep-lit` | | Leave the last colour on at exit |

Slow and dim, for a desk:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.color_cycle \
  --hold 3 --fade 1.5 --max-brightness 0.3
```

## It runs alongside the head

The servos are on the UART bus and the light is on GPIO18, so nothing here
touches `mio-head.service` and there is no need to stop it. That is the
opposite of the firmware tools, where two processes on one bus fight over the
servos.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `Cannot import the LED stack` | Running outside `~/ledenv`, or not on the Pi |
| `Cannot reach the PIO device` | `/dev/pio0` missing; update the firmware |
| `Permission denied` | Run with `sudo -E`, or join the group owning `/dev/pio0` |
| Colours named wrong | Byte order; try `--order RGB` or `BGR` |
| Flicker, or nothing at all | 3.3 V data into a 5 V part; add a level shifter |
| Dim colours look washed | `--gamma 0` was passed, or the ceiling is very low |

## Tests

The colour logic is separate from the hardware and tested off the Pi:

```bash
uv run --frozen pytest tests/test_color_cycle.py tests/test_eyes.py
```


# The eyes

Two white LEDs on GPIO23 and GPIO24, run from `gpiozero`:

```bash
cd ~/mio-core-services-waveshare
~/ledenv/bin/python -m mio_core_services.lighting.eyes
```

The default is `--mode alternate`: the left eye blinks on its own for three
seconds, then the right eye blinks on its own for three seconds. They are
never lit at the same time. Six seconds a lap, repeating until Ctrl+C.

The earlier pattern is still there as `--mode flashes` — left three times,
right three times, then both together for three seconds:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.eyes --mode flashes
```

Both LEDs are driven off and the pins released on the way out, including on
SIGTERM, so a systemd unit stops cleanly too.

**Which eye is "left"** depends on how they were soldered and whether you mean
the robot's left or the one facing you. If the wrong one goes first, swap them:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.eyes --left-pin 24 --right-pin 23
```

If that is the right way round, change `DEFAULT_LEFT_PIN` and
`DEFAULT_RIGHT_PIN` in `mio_core_services/lighting/eyes.py`.

## Options

| Flag | Default | |
| --- | --- | --- |
| `--left-pin` | 23 | BCM number, pin 16 |
| `--right-pin` | 24 | BCM number, pin 18 |
| `--mode` | `alternate` | `alternate` or `flashes` |
| `--each-seconds` | 3.0 | alternate: seconds each eye holds the floor |
| `--flashes` | 3 | flashes: flashes per eye before the pair blink |
| `--flash-on` / `--flash-off` | 0.12 / 0.18 | Flash timing |
| `--gap` | 0.45 | Dark pause between phases |
| `--both-seconds` | 3.0 | flashes: how long the pair blink together |
| `--blink-on` / `--blink-off` | 0.15 | Blink timing, either mode |
| `--laps` | 0 | Laps to run; 0 until stopped |
| `--active-low` | | If the LEDs sink rather than source |

Every timed phase is trimmed to length rather than rounded up to a whole
blink cycle, so an awkward value lasts exactly what you asked for.

If the eyes come on when they should be off, they are wired to sink current —
pass `--active-low`.

## Running everything at once

Nothing is shared: the servos are on the UART, the RGB light is on GPIO18 and
the eyes are on GPIO23/24.

```bash
~/ledenv/bin/python -m mio_core_services.lighting.eyes &
~/ledenv/bin/python -m mio_core_services.lighting.color_cycle
```

Stop the cycle with Ctrl+C, then bring the eyes back with `fg` and Ctrl+C, or
`kill %1`. Backgrounding it that way means it dies with the SSH session; a
`systemd` unit like `mio-head.service` is the answer if you want it permanent.

## Eye troubleshooting

| Symptom | Cause |
| --- | --- |
| `Cannot import gpiozero` | `sudo apt install -y python3-gpiozero python3-lgpio` |
| `Cannot claim GPIO` | Another process holds the pins, or no gpio group |
| Wrong eye flashes first | Swap `--left-pin` and `--right-pin` |
| Inverted, on when off | `--active-low` |
