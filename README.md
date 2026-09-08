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

# Waveshare HAT (A) Servo Calibration

Full setup, flashing instructions, and troubleshooting live in
[docs/waveshare-servo-hat.md](docs/waveshare-servo-hat.md). Read that first if
the servos do not respond.

Two prerequisites, both one-time and both required on a factory-fresh board:

1. The ESP32 must be running Waveshare's transparent-transmission firmware. The
   stock firmware serves a WiFi control page and discards packets arriving on
   the UART.
2. On a Raspberry Pi 5, the GPIO UART must be enabled with `dtparam=uart0=on`
   and addressed as `/dev/ttyAMA0`. Do not use `/dev/serial0` — on a Pi 5 it
   points at the debug header, not at GPIO 14/15.

With the HAT switch in ESP32 mode, the Pi talks to the ESP32 at 115,200 baud
and the ESP32 forwards native STS3215 packets to the servo bus at 1,000,000
baud. This is not the JSON protocol used by other Waveshare boards.

With exactly one servo connected, make a non-moving read to confirm that ID 1
and the transparent link work:

```bash
uv run --frozen python -m mio_core_services.firmware.read_servo \
  --port /dev/ttyAMA0 --baudrate 115200 --id 1 --diagnose
```

New STS3215 servos normally share ID 1. Leave the first (tilt) servo as ID 1.
Power off, connect only the second (pan) servo, power on, verify it as ID 1,
then assign it ID 2:

```bash
uv run --frozen python -m mio_core_services.firmware.encode_servo_id \
  --port /dev/ttyAMA0 --baudrate 115200 --current-id 1 --new-id 2
```

Power off, connect both servos to the same bus, and power on. Verify both IDs
before allowing movement:

```bash
uv run --frozen python -m mio_core_services.firmware.read_servo \
  --port /dev/ttyAMA0 --baudrate 115200 --id 1
uv run --frozen python -m mio_core_services.firmware.read_servo \
  --port /dev/ttyAMA0 --baudrate 115200 --id 2
```

Finally, interactively jog each servo to the mechanism's physical zero and
save the zero and travel limits:

```bash
uv run --frozen python -m mio_core_services.firmware.zero_servos \
  --port /dev/ttyAMA0 --baudrate 115200 \
  --output servo_zeros.json 1 2
```
