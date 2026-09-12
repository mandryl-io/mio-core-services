# RGB Lighting

A WS2811 RGB light on GPIO18, cycling the three primaries and then the full
spectrum, changing brightness on every transition.

## Wiring

| Breakout | Pi 5 header | |
| --- | --- | --- |
| 5V | physical pin 2 | 5V |
| GND | physical pin 6 | ground |
| DI | physical pin 12 | GPIO18, `board.D18` in software |

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
uv run --frozen pytest tests/test_color_cycle.py
```
