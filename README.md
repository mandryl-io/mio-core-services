# To Run

Ensure you have `uv`, run `uv sync` to install the dependencies.

Then, run `uv run main.py` to start the pipeline example.

# Tests

Unit tests:

```
uv run pytest
```

Scenarios live in `tests/scenarios/` and are run with [Pipecat evals](https://docs.pipecat.ai/pipecat/evals/overview), not pytest. Install the CLI once if you do not have it (`uv tool install "pipecat-ai[cli]"`).

Start the agent on the eval transport in one terminal:

```
uv run main.py -t eval
```

In another terminal, run every scenario:

```
pipecat eval run tests/scenarios/*.yaml
```

The default judge is Ollama (`gemma2:9b`). Pull it with `ollama pull gemma2:9b` if needed.

# Servos

Two STS3215 bus servos on a Waveshare `Bus Servo Driver HAT (A)`:

| ID | Axis | Joint |
| --- | --- | --- |
| 1 | Yaw | Neck |
| 2 | Pitch | Head |

- **[docs/servo-calibration.md](docs/servo-calibration.md)** — the calibration
  workflow and every firmware tool.
- **[docs/waveshare-servo-hat.md](docs/waveshare-servo-hat.md)** — HAT setup,
  ESP32 firmware flashing, and link troubleshooting.

A factory-fresh HAT will not work over the GPIO UART until the ESP32 is flashed
with Waveshare's transparent-transmission firmware, and a Raspberry Pi 5 needs
`dtparam=uart0=on` with `/dev/ttyAMA0` named explicitly — `/dev/serial0` points
at the debug header there. Both are one-time steps, covered in the HAT doc.

Check the bus first:

```bash
uv run --frozen python -m mio_core_services.firmware.scan_servos
```

Then calibrate a joint — record its zero with the part fitted, set the travel
limits, and rehearse them:

```bash
uv run --frozen python -m mio_core_services.firmware.set_zero --id 1
uv run --frozen python -m mio_core_services.firmware.calibrate_range --id 1
uv run --frozen python -m mio_core_services.firmware.check_limits --cycles 1
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
