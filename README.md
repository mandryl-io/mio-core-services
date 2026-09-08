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
