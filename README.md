# To Run

Ensure you have `uv`, run `uv sync` to install the dependencies.
Install the LiveKit CLI once on Linux:

```
sudo apt-get install -y jq
curl -sSL https://get.livekit.io/cli | bash
```

# Conversation (LiveKit)

The spoken conversation service is a thin LiveKit STT→LLM→TTS agent. Put these
in `.env`:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `MIO_SYSTEM_PROMPT_PATH` (optional; defaults to `prompts/default.md`)

Download local inference files once:

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

The pipeline remains unchanged from the experiment: its
`inference.TurnDetector` still uses LiveKit's hosted inference gateway.

On the Pi, `mio-wifi.service` runs first and either joins saved WiFi or
raises a setup hotspot. `mio-conversation.service` starts the same console
path once that has finished and the network is online. Stop conversation
before running console manually so two processes do not share the audio
devices:

```bash
sudo systemctl stop mio-conversation.service
make run-conversation-service
```

The service starts again on the next boot. To keep it disabled across reboots,
use `sudo systemctl disable --now mio-conversation.service`; restore it with
`sudo systemctl enable --now mio-conversation.service`. See
[deploy/README.md](deploy/README.md).

# WiFi setup

If the Pi has no home network at boot, the eyes fade slowly on and off until
someone joins **Mio-Setup** (password `miosetup`) and picks a network in the
phone page at `http://10.42.0.1`. That page lives in [`app/`](app/). Head,
idle blink, and conversation wait until this finishes. Details are in
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
idle-blink on boot via `mio-eyes.service` once WiFi setup has released the
pins: both stay open, then close together for a short human-length blink
every few seconds. Timing is in `config/blink.yaml`. While the setup hotspot
is up, `mio-wifi.service` fades both eyes slowly instead. The older demo
patterns (`--mode alternate` / `flashes`) are still in `lighting.eyes` if
you want them:

```bash
~/ledenv/bin/python -m mio_core_services.lighting.idle_blink
```

Swap `--left-pin` and `--right-pin` if the wrong eye is mapped. The RGB light,
the eyes and the head all run at once; they share no hardware.
