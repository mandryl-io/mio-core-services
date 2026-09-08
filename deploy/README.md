# Running the head on boot

`mio-head.service` starts `idle_motion` at power-on: slow centring, a full
range-of-motion sweep, then continuous idle behaviour. It needs no network, no
SSH session and nobody logged in.

## One-shot install

```bash
bash deploy/apply-and-reboot.sh
```

Stops anything on the bus, pulls, restores the reviewed register baseline on
both servos, writes and verifies the hard travel limits, enables the service,
and reboots.

## Install manually

On the Pi, from the repository:

```bash
sudo cp deploy/mio-head.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mio-head.service
sudo systemctl start mio-head.service
```

Check it:

```bash
systemctl status mio-head.service
journalctl -u mio-head.service -f
```

Then prove the real thing:

```bash
sudo reboot
```

## Before enabling it

The service reads `servo_zeros.json` from the working directory and refuses to
move unless each servo's EEPROM limits match it, so calibrate and write the
limits first:

```bash
uv run --frozen python -m mio_core_services.firmware.apply_limits --verify
```

## Running tools by hand

Two processes on one bus fight over the servos. Stop the service first:

```bash
sudo systemctl stop mio-head
# ... work ...
sudo systemctl start mio-head
```

## Paths

The unit hardcodes `/home/mio/mio-core-services-waveshare` and the `mio` user.
Change `WorkingDirectory`, `ExecStart` and `User` together if either differs.

`ExecStart` uses the virtualenv's interpreter rather than `uv run`, so start-up
does not depend on `uv` being on a non-interactive `PATH`, and cannot stall
resolving dependencies with no network.

## Behaviour on stop and failure

`KillSignal=SIGTERM` with `TimeoutStopSec=15` lets `idle_motion` centre the head
and release torque before exiting. `Restart=always` with `RestartSec=5` brings
it back if it crashes, and covers the case where the serial device is not ready
at the instant the service first starts.
