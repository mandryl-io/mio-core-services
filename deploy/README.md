# Running WiFi setup, the head, eyes, and conversation on boot

`mio-wifi.service` starts first. It waits briefly for an existing home WiFi
lease. If the Pi is already online, the unit exits and the rest of the robot
starts. If not, it raises a **Mio-Setup** hotspot (password `miosetup`), fades
the eyes slowly on and off, and serves the phone page in [`app/`](../app/).
Join that hotspot, open `http://10.42.0.1`, pick a home network. When Mio
joins it, the hotspot and eye fade stop, the pins are released, and the other
units start.

`mio-head.service` then starts `firmware.runtime.idle_motion`: slow
centring, a full range-of-motion sweep, then continuous idle behaviour.

`mio-eyes.service` starts `lighting.idle_blink` after WiFi setup has released
GPIO23/24: both eyes stay open, then close together for a human-length blink
every few seconds. The head and idle blink share no hardware — servos on the
UART, eyes on GPIO23/24.

`mio-conversation.service` starts the LiveKit STT→LLM→TTS agent in local
console mode, using the Pi microphone and speaker. A dedicated virtual terminal
keeps LiveKit's console runner usable without a login session. It needs the
network and a `.env` with `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY`. The unit is
still installed if `.env` is missing; it will fail until those keys are present.

Head and idle blink still need no SSH session and nobody logged in; they wait
on `mio-wifi.service` so setup can finish first. Conversation waits for
`mio-wifi.service` and `network-online.target`.

## One-shot install

Install the LiveKit CLI once:

```bash
sudo apt-get install -y jq
curl -sSL https://get.livekit.io/cli | bash
```

Then apply the deployment:

```bash
bash deploy/apply-and-reboot.sh
```

Stops anything on the bus, the eyes, WiFi setup, or the conversation mic;
pulls; syncs the venv; downloads LiveKit local files; restores the reviewed
register baseline on both servos; writes and verifies the hard travel limits;
enables all four boot services; and reboots.

## Install manually

On the Pi, from the repository:

```bash
sudo cp deploy/mio-wifi.service deploy/mio-head.service deploy/mio-eyes.service deploy/mio-conversation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mio-wifi.service mio-head.service mio-eyes.service mio-conversation.service
sudo systemctl start mio-wifi.service mio-head.service mio-eyes.service mio-conversation.service
```

Check it:

```bash
systemctl status mio-wifi.service mio-head.service mio-eyes.service mio-conversation.service
journalctl -u mio-wifi.service -u mio-head.service -u mio-eyes.service -u mio-conversation.service -f
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
uv run python -m livekit.agents download-files
```

## Running tools by hand

Two processes on one bus fight over the servos; two processes on GPIO23/24
fight over the eyes; two conversation processes fight over the mic. Stop the
matching service first. `mio-wifi` only holds the eye pins while the setup
hotspot is up; the normal path releases them before `mio-eyes` starts.

```bash
sudo systemctl stop mio-head
# ... servo work ...
sudo systemctl start mio-head

sudo systemctl stop mio-eyes
# ... eye work ...
sudo systemctl start mio-eyes

sudo systemctl stop mio-wifi
# ... eye work while setup would otherwise own the lamps ...
sudo systemctl start mio-wifi

sudo systemctl stop mio-conversation
# ... manual `lk agent console mio_core_services/conversation.py` ...
sudo systemctl start mio-conversation
```

## Paths

The unit hardcodes `/home/mio/mio-core-services-waveshare` and the `mio` user.
Change `WorkingDirectory`, `ExecStart` and `User` together if either differs.

The head and conversation units use the repository `.venv`. The eyes unit and
the WiFi bootstrap use `~/ledenv`, which sees system `gpiozero`; `.venv` does
not. WiFi setup runs as root so it can raise the hotspot and bind port 80.
None of them use `uv run`, so start-up does not depend on `uv` being on a
non-interactive `PATH`, and cannot stall resolving dependencies with no
network.

## Behaviour on stop and failure

`KillSignal=SIGTERM` with `TimeoutStopSec=15` lets `idle_motion` centre the head
and release torque before exiting. The eyes unit uses 5 s: `idle_blink` turns
the lamps off and releases the pins. WiFi setup uses 10 s so it can drop the
hotspot and release the same pins. Conversation uses 15 s so the LiveKit
session can drain. `Restart=always` with `RestartSec=5` brings head, eyes, or
conversation back if they crash, and covers the case where the serial device,
gpiochip, or network is not ready at the instant the service first starts.
WiFi setup is a oneshot (`TimeoutStartSec=infinity`) so it can wait for a
person to pick a network.
