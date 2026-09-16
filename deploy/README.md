# Running the head, eyes, and conversation on boot

`mio-head.service` starts `firmware.runtime.idle_motion` at power-on: slow
centring, a full range-of-motion sweep, then continuous idle behaviour.

`mio-eyes.service` starts `lighting.idle_blink` alongside it: both eyes stay
open, then close together for a human-length blink every few seconds. The two
units share no hardware — servos on the UART, eyes on GPIO23/24.

`mio-conversation.service` starts the LiveKit STT→LLM→TTS agent in console
mode. It needs the network and a `.env` with `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`, and `OPENAI_API_KEY`. The unit is still installed if
`.env` is missing; it will fail until those keys are present.

Head and eyes need no network, no SSH session and nobody logged in.
Conversation waits for `network-online.target`.

## One-shot install

```bash
bash deploy/apply-and-reboot.sh
```

Stops anything on the bus, the eyes, or the conversation mic; pulls; syncs
the venv; downloads LiveKit local files; restores the reviewed register
baseline on both servos; writes and verifies the hard travel limits; enables
all three boot services; and reboots.

## Install manually

On the Pi, from the repository:

```bash
sudo cp deploy/mio-head.service deploy/mio-eyes.service deploy/mio-conversation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mio-head.service mio-eyes.service mio-conversation.service
sudo systemctl start mio-head.service mio-eyes.service mio-conversation.service
```

Check it:

```bash
systemctl status mio-head.service mio-eyes.service mio-conversation.service
journalctl -u mio-head.service -u mio-eyes.service -u mio-conversation.service -f
```

Then prove the real thing:

```bash
sudo reboot
```

## Before enabling it

The head service reads `servo_zeros.json` from the working directory and
refuses to move unless each servo's EEPROM limits match it, so calibrate and
write the limits first:

```bash
uv run --frozen python -m mio_core_services.firmware.calibration.apply_limits --verify
```

Conversation needs a simple `KEY=value` `.env` (systemd `EnvironmentFile`
does not accept `export` syntax). Download local inference files once after
`uv sync`:

```bash
uv run python -m mio_core_services.conversation download-files
```

## Running tools by hand

Two processes on one bus fight over the servos; two processes on GPIO23/24
fight over the eyes; two conversation processes fight over the mic. Stop the
matching service first:

```bash
sudo systemctl stop mio-head
# ... servo work ...
sudo systemctl start mio-head

sudo systemctl stop mio-eyes
# ... eye work ...
sudo systemctl start mio-eyes

sudo systemctl stop mio-conversation
# ... manual `python -m mio_core_services.conversation console` ...
sudo systemctl start mio-conversation
```

## Paths

The unit hardcodes `/home/mio/mio-core-services-waveshare` and the `mio` user.
Change `WorkingDirectory`, `ExecStart` and `User` together if either differs.

The head and conversation units use the repository `.venv`. The eyes unit uses
`~/ledenv`, which sees system `gpiozero`; `.venv` does not. None of them use
`uv run`, so start-up does not depend on `uv` being on a non-interactive
`PATH`, and cannot stall resolving dependencies with no network.

## Behaviour on stop and failure

`KillSignal=SIGTERM` with `TimeoutStopSec=15` lets `idle_motion` centre the head
and release torque before exiting. The eyes unit uses 5 s: `idle_blink` turns
the lamps off and releases the pins. Conversation uses 15 s so the LiveKit
session can drain. `Restart=always` with `RestartSec=5` brings any of them
back if they crash, and covers the case where the serial device, gpiochip, or
network is not ready at the instant the service first starts.
