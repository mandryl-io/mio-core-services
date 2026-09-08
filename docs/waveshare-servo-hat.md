# Waveshare Bus Servo Driver HAT (A) — Setup and Troubleshooting

How the STS3215 bus servos are driven from the Raspberry Pi, the one-time
setup a factory-fresh HAT needs, and a log of the faults we hit getting there.

## Verified working configuration

| Item | Value |
| --- | --- |
| Board | Raspberry Pi 5 Model B Rev 1.1 |
| OS | Raspberry Pi OS (Debian trixie), kernel 6.12.47 |
| HAT | Waveshare `Bus Servo Driver HAT (A)`, ESP32-WROOM-32 |
| Serial port | `/dev/ttyAMA0` (GPIO 14/15) |
| Baud rate | 115200 (host to ESP32; the ESP32 talks to the servos at 1 Mbps) |
| Mode switch | ESP32 position |
| ESP32 firmware | `ServoDriverST.ino.bin` (transparent transmission) |
| Servo power | HAT's own external supply — the Pi's 5 V does not drive the bus |

Reading a position with this configuration:

```bash
uv run --frozen python -m mio_core_services.firmware.read_servo \
  --port /dev/ttyAMA0 --baudrate 115200 --id 1 --diagnose
```

## One-time setup

A factory-fresh HAT will not work over the GPIO UART. Both steps below are
required, and neither is optional.

### 1. Enable the GPIO UART (Raspberry Pi 5 only)

On a Pi 5, `/dev/serial0` points at the **debug** connector (`/dev/ttyAMA10`),
not at GPIO 14/15 where the HAT sits. Writing to it transmits out the wrong
physical pins, silently. The GPIO UART is a separate device that must be
enabled explicitly.

Add to `/boot/firmware/config.txt` and reboot:

```
dtparam=uart0=on
```

That creates `/dev/ttyAMA0`. Note the symlink does not follow: `/dev/serial0`
still points at `ttyAMA10` afterwards, so always name `/dev/ttyAMA0`
explicitly. Confirm the pins are muxed to the UART (`raspi-gpio` does not
exist on Pi 5 — use `pinctrl`):

```bash
pinctrl get 14,15
# 14: a4    pn | hi // GPIO14 = TXD0
# 15: a4    pu | hi // GPIO15 = RXD0
```

### 2. Flash the transparent-transmission firmware

The HAT ships with `BusServoDriverHAT.ino.bin`, a WiFi/web demo that serves a
control page over its own access point. That firmware **discards raw Feetech
packets arriving on the UART**, so the Pi cannot reach the servos through it.

Waveshare's instructions use a Windows-only `flash_download_tool_3.9.5.exe`.
`esptool` does the same job on macOS or Linux.

Download and unpack the transparent-transmission package:

```bash
curl -LO https://files.waveshare.com/wiki/Bus_Servo_Driver_HAT_A/Bus_Servo_Driver_HAT_A.zip
unzip Bus_Servo_Driver_HAT_A.zip
cd "Bus Servo Driver HAT (A)/Bus Servo Driver HAT (A)/bin"
```

The HAT's USB-C ports are physically blocked by the Pi's own USB sockets when
it is mounted, so **lift the HAT off the Pi** and connect its ESP32 USB-C port
to your computer. Confirm the chip is reachable, and check the MAC matches the
board you expect:

```bash
esptool --port /dev/cu.usbmodemXXXXXXX --baud 115200 chip-id
```

Flash. The four offsets come from Waveshare's own `configure/esp32/multi_download.conf`:

```bash
esptool --chip esp32 --port /dev/cu.usbmodemXXXXXXX --baud 460800 write-flash -z \
  0x1000  bootloader_dio_40m.bin \
  0x8000  default.bin \
  0xe000  boot_app0.bin \
  0x10000 ServoDriverST.ino.bin
```

Look for `Hash of data verified.` on each image. Then refit the HAT, reconnect
the servo power, and verify:

```bash
uv run --frozen python -m mio_core_services.firmware.read_servo \
  --port /dev/ttyAMA0 --baudrate 115200 --id 1 --diagnose
```

Transparent transmission is automatic once flashed. The old firmware's
"Start Serial Forwarding" web button is **not** needed and does not apply.

## Telling the two firmwares apart

Both builds print near-identical boot banners, so the banner alone cannot
identify which is loaded. The factory build announces its access point:

```
MAC:88:F1:55:0B:67:54
AP IP address: 192.168.4.1
Server Starts.
----------->1<-----------
ID:
1
```

After flashing the transparent build, the board no longer prints this banner
on the Pi's UART. Silence at boot plus a successful position read is the
signal that the flash took.

To capture the banner, listen on the Pi while power-cycling the HAT:

```bash
python3 -c "
import serial, time
s = serial.Serial('/dev/ttyAMA0', 115200, timeout=1)
end = time.time() + 20
while time.time() < end:
    d = s.read(256)
    if d: print(repr(d))
"
```

## Troubleshooting

### `rx=empty` — no bytes returned at all

`read_servo` reports this when the UART opened and transmitted but nothing came
back. Work down this list in order; each step rules out a layer.

1. **Wrong port.** On a Pi 5, is the command naming `/dev/ttyAMA0` rather than
   `/dev/serial0`? Check `ls -l /dev/serial0` — if it resolves to `ttyAMA10`,
   traffic is going to the debug header.
2. **Pin mux.** `pinctrl get 14,15` should report `TXD0` and `RXD0`.
3. **Is the Pi transmitting?** At 115200 8N1, writing 23,040 bytes takes about
   two seconds of real time. If the call returns instantly, nothing is leaving
   the pin.

   ```bash
   python3 -c "
   import serial, time
   s = serial.Serial('/dev/ttyAMA0', 115200, timeout=1)
   t = time.monotonic(); s.write(b'U' * 23040); s.flush()
   print('%.2fs' % (time.monotonic() - t))
   "
   ```

4. **Loopback.** Power down, remove the HAT, jumper header pin 8 to pin 10,
   boot, and write then read on `/dev/ttyAMA0`. An echo proves the Pi's UART is
   healthy in both directions and moves suspicion to the HAT.
5. **Firmware.** If the Pi is healthy, the board is almost certainly still on
   the factory firmware. Flash it (above).
6. **Servo power and ID.** The factory firmware scans the bus at boot and
   prints what it finds (`ID:` followed by the IDs), which confirms power,
   wiring, and IDs independently of the Pi.

### Cross-checking against Waveshare's own client

If our client fails, build Waveshare's reference and compare. Identical
behaviour from both points at hardware rather than our code:

```bash
wget https://files.waveshare.com/wiki/Bus_Servo_Driver_HAT_A/SCServo_Linux.rar
sudo apt install -y libarchive-tools cmake build-essential
bsdtar -xf SCServo_Linux.rar
cd SCServo_Linux_220329/SCServo_Linux && cmake . && make SCServo
cd examples/SMS_STS/Ping && cmake . && make
sudo ./Ping /dev/ttyAMA0     # prints "ID:1" when the link works
```

Our framing in `mio_core_services/firmware/sts3215.py` matches that reference
exactly — same `0xff 0xff ID LEN FUN ...` header, same `~(sum)` checksum, same
little-endian word order, same 115200 default in the SMS/STS examples.

### `uv: command not found` over SSH

Non-interactive SSH does not load the profile that puts `uv` on `PATH`. Use the
absolute path:

```bash
ssh -t mio@raspberrypi.local 'cd ~/mio-core-services-waveshare && ~/.local/bin/uv run --frozen ...'
```

### Reads work but the servo does not move

Position reads draw far less current than motion. Check the HAT's external
supply before suspecting the command path.

## Known gaps in the firmware CLIs

`move_servo`, `sweep_servos`, `zero_servos`, and `teleop_servo` accept `--port`
but not `--baudrate`, so they construct the bus at `DEFAULT_BAUDRATE`
(1,000,000) and will time out on this HAT, which needs 115200. Only
`read_servo` and `encode_servo_id` take `--baudrate` today.

## Debugging log

The session that produced this document, in order, for anyone hitting the same
wall. Three independent faults were stacked, and each one masked the next.

| # | Symptom | Finding |
| --- | --- | --- |
| 1 | `rx=empty` on `/dev/serial0` at 115200 | `/dev/serial0` resolved to `/dev/ttyAMA10`, the Pi 5 debug header. Wrong physical pins. |
| 2 | `rx=empty` on `/dev/ttyAMA0` too | `dtparam=uart0=on` was already set and `pinctrl` confirmed `TXD0`/`RXD0`, so the port was now right but something downstream was silent. |
| 3 | No USB serial node for the HAT | `DEFAULT_PORT = /dev/ttyACM0` in `sts3215.py` is a leftover from USB-mode work. The HAT's USB-C ports are blocked by the Pi's USB sockets when mounted, so USB mode was unavailable. |
| 4 | Silence at every baud from 9600 to 1 Mbps | A live link with the wrong baud yields framing garbage, not silence. Eleven clean silences excluded a baud mismatch. |
| 5 | ESP32 boot log captured on the Pi's RX | Proved ESP32 → Pi worked, and that servo ID 1 was powered and answering (`ID: 1` from the firmware's own bus scan). Narrowed the fault to Pi → ESP32. |
| 6 | Waveshare's `Ping` binary failed identically | Excluded our protocol implementation entirely. |
| 7 | TX timing 2.01 s, loopback echoed | Pi UART healthy in both directions. Fault was on the HAT. |
| 8 | Flashed `ServoDriverST.ino.bin` | `Ping` returned `ID:1` and `read_servo` returned a position. Resolved. |

Two dead ends worth recording, so they are not repeated:

- **The "Start Serial Forwarding" web button.** The factory firmware exposes it
  at `http://192.168.4.1/cmd?inputT=1&inputI=14&inputA=0&inputB=0`. It does not
  enable UART forwarding for the Pi, and the transparent firmware does not need
  it.
- **Comparing firmware by strings.** Both builds contain `AP IP address:`,
  `Server Starts.`, `ESP32_DEV`, and `Serial Forwarding`, so a string match does
  not tell you which is flashed. Only `SERIAL_FORWARDING` differs, and it is not
  visible at runtime.
