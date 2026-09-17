# To Run

You need `uv` and the LiveKit CLI (`lk`). The CLI is a prerequisite: the
conversation service is started with `lk agent console`. Then run `uv sync`
to install Python dependencies.

## LiveKit CLI

On a Mac, this Makefile target installs the CLI with Homebrew, installs `uv`
if it is missing, syncs the venv, and downloads local inference files:

```
make setup-dev-osx
```

To install the CLI by itself on a Mac:

```
brew install livekit-cli
```

On Linux:

```
sudo apt-get install -y jq
curl -sSL https://get.livekit.io/cli | bash
```

# Conversation (LiveKit)

The spoken conversation service is a thin LiveKit STT→LLM→TTS agent using
Deepgram Nova-3 STT and OpenAI TTS. Put these in `.env`:

- `DEEPGRAM_API_KEY`
- `OPENAI_API_KEY`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `MIO_SYSTEM_PROMPT_PATH` (optional; defaults to `prompts/default.md`)

`BASETEN_API_KEY` is read from the process environment. Set it at OS/root
level (for example `/etc/environment` or `/etc/default/mio`) so it is not
tied to the repo `.env`. A value already in the process environment wins
over `.env`. The LLM is GLM 5.3 on Baseten's OpenAI-compatible endpoint
(`zai-org/GLM-5.3`); barge-in is on via Silero VAD and adaptive
interruption.

Download local inference files once (`make setup-dev-osx` already does this):

```
uv run python -m livekit.agents download-files
```

`console` runs the experimental pipeline against the local microphone and
speaker without joining a LiveKit room:

```
make run-conversation-service
# or
MIO_SYSTEM_PROMPT_PATH=prompts/default.md \
  lk agent console mio_core_services/conversation.py
```

On a Mac, use the `lk agent console` form so you are not bound to the Pi USB
device names in `run-conversation-service`.

The turn detector still uses LiveKit's hosted inference gateway. Barge-in
uses local Silero VAD plus adaptive interruption so the person can talk
over Mio.

On the Pi, `mio-conversation.service` starts the same console path at boot.
Stop it before running console manually so two processes do not share the
audio devices:

```bash
sudo systemctl stop mio-conversation.service
make run-conversation-service
```

The service starts again on the next boot. To keep it disabled across reboots,
use `sudo systemctl disable --now mio-conversation.service`; restore it with
`sudo systemctl enable --now mio-conversation.service`. See
[deploy/README.md](deploy/README.md).

# Tests

```
uv run pytest
```

# Servos

Two STS3215 bus servos on a Waveshare `Bus Servo Driver HAT (A)`:

| ID | Axis | Joint |
| --- | --- | --- |
| 1 | Yaw | Neck |
| 2 | Pitch | Head |

- **[docs/servo-calibration.md](docs/servo-calibration.md)** — the calibration
  workflow and firmware tools, grouped as setup, calibration, runtime, and
  tuning.
- **[docs/waveshare-servo-hat.md](docs/waveshare-servo-hat.md)** — HAT setup,
  ESP32 firmware flashing, and link troubleshooting.

A factory-fresh HAT will not work over the GPIO UART until the ESP32 is flashed
with Waveshare's transparent-transmission firmware, and a Raspberry Pi 5 needs
`dtparam=uart0=on` with `/dev/ttyAMA0` named explicitly — `/dev/serial0` points
at the debug header there. Both are one-time steps, covered in the HAT doc.

Check the bus first:

```bash
uv run --frozen python -m mio_core_services.firmware.setup.scan_servos
```

Then calibrate a joint — record its zero with the part fitted, set the travel
limits, and rehearse them:

```bash
uv run --frozen python -m mio_core_services.firmware.calibration.set_zero --id 1
uv run --frozen python -m mio_core_services.firmware.calibration.calibrate_range --id 1
uv run --frozen python -m mio_core_services.firmware.calibration.check_limits --cycles 1
```

Results land in `servo_zeros.json`. The last two read the arrow keys, so over
SSH they need `ssh -t`.

# Lighting

A WS2811 RGB light on GPIO18 (physical pin 12), 5V and ground from pins 2 and
6. It runs on the Pi 5's PIO block, not the old `rpi_ws281x` route, which does
not work on this board.

- **[docs/rgb-lighting.md](docs/rgb-lighting.md)** — wiring, the one-time
  library setup, and every option.

The stack lives in its own virtualenv (`~/ledenv`, with system site packages),
kept out of `pyproject.toml` so `uv.lock` and the `--frozen` servo commands
stay valid. Check the byte order before anything else — WS2811 breakouts do
not agree on it:

```bash
cd ~/mio-core-services-waveshare
~/ledenv/bin/python -m mio_core_services.lighting.color_cycle --check-order
```

Then run the cycle — red, green, blue, then ROYGBIV, stepping brightness on
every transition:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.color_cycle
```

It shares no hardware with the servos, so `mio-head.service` can keep the head
moving while it runs.

Two white eye LEDs on GPIO23 and GPIO24 (pins 16 and 18, grounds on pin 14)
idle-blink on boot via `mio-eyes.service`: both stay open, then close together
for a short human-length blink every few seconds. Timing is in
`config/blink.yaml`. The older demo patterns (`--mode alternate` / `flashes`)
are still in `lighting.eyes` if you want them:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.idle_blink
```

Swap `--left-pin` and `--right-pin` if the wrong eye is mapped. The RGB light,
the eyes and the head all run at once; they share no hardware.
