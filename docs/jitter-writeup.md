# STS3215 head jitter — how the motion is driven

A description of the control stack for a two-axis robot head, written for
someone diagnosing residual servo jitter. Everything below is the current
state of the code; the problem is unresolved.

## Symptom

Two Feetech STS3215 servos visibly buzz and hunt. Reported both while
travelling and while holding a position. It is not uniform — it appears in some
angular sectors of the yaw travel and not others.

## Hardware

| | |
| --- | --- |
| Host | Raspberry Pi 5, Raspberry Pi OS (Debian trixie), kernel 6.12.47 |
| Driver board | Waveshare `Bus Servo Driver HAT (A)`, ESP32-WROOM-32 |
| ESP32 firmware | Waveshare transparent transmission (`ServoDriverST.ino.bin`) |
| Host link | `/dev/ttyAMA0` (GPIO 14/15), **115200 baud**, 8N1 |
| Servo bus | ESP32 forwards to the STS3215 bus at **1,000,000 baud** |
| Servos | STS3215, 12 V variant, reading 12.2 V at the servo |
| Axis 1 | Neck yaw, carries the head. Range 637–3711, zero 1658 |
| Axis 2 | Head pitch. Range 1450–1890, zero 1675 |

Encoder is 4096 counts per revolution, so **11.38 ticks/degree**, 0.088°/tick.

The Pi does not talk to the servos directly. Every packet crosses the GPIO UART
at 115200 into the ESP32, which re-transmits it onto the 1 Mbps servo bus. That
adds latency and a second failure surface we cannot observe.

## Protocol layer

Standard Feetech framing, verified byte-for-byte against Waveshare's own
`SCServo_Linux` reference (their `Ping` and ours emit identical bytes).

```python
def _checksum(body: bytes) -> int:
    return (~sum(body)) & 0xFF


def _packet(servo_id: int, instruction: int, params: bytes = b"") -> bytes:
    length = len(params) + 2
    body = bytes([servo_id, length, instruction]) + params
    return bytes([0xFF, 0xFF]) + body + bytes([_checksum(body)])
```

Serial port setup:

```python
ser = serial.Serial()
ser.port = "/dev/ttyAMA0"
ser.baudrate = 115200
ser.timeout = 0.1
ser.write_timeout = 0.1
ser.dtr = False
ser.open()
```

Register writes. Note the `reset_input_buffer()` after every write — this
discards the servo's ACK rather than reading it:

```python
def _write(self, servo_id: int, address: int, data: bytes) -> None:
    self._serial.write(write_packet(servo_id, address, data))
    self._serial.flush()
    self._serial.reset_input_buffer()
```

Goals go out as a broadcast SYNC_WRITE to address 42, so both axes move on one
packet:

```python
def set_goals(self, goals: dict[int, int]) -> None:
    payload = bytearray([ADDR_GOAL_POSITION, 2])
    for servo_id, position in goals.items():
        payload.extend([servo_id, position & 0xFF, (position >> 8) & 0xFF])
    self._serial.write(_packet(BROADCAST_ID, INST_SYNC_WRITE, bytes(payload)))
    self._serial.flush()
    self._serial.reset_input_buffer()
```

Speed and acceleration are set before a move, then torque enabled:

```python
def prepare(self, servo_id: int = 1, speed: int = 1000, acc: int = 50) -> None:
    self._write(servo_id, ADDR_ACC, bytes([acc]))          # addr 41
    self._write(servo_id, ADDR_GOAL_SPEED,                  # addr 46, 2 bytes
                bytes([speed & 0xFF, (speed >> 8) & 0xFF]))
    self.enable_torque(servo_id, True)                      # addr 40
```

Position reads use INST_READ on address 56, with up to 5 attempts and a 0.15 s
window each.

## How motion is commanded

### Originally — micro-stepping (this was the first bug)

A held arrow key advanced the goal a few ticks every 20 ms:

```python
position = position + direction * step   # step = 5
bus.set_goal(position, servo_id=servo_id)
```

At 50 Hz with speed commanded at 2400 the servo reached each goal almost
instantly, stopped, and waited — a complete accelerate/decelerate cycle fifty
times a second. Removing this improved things but did not eliminate the jitter.

### Now — one goal per direction change

```python
def steer(self, direction: int) -> None:
    if direction == self._direction:
        return
    if direction == 0:
        self.stop()
    else:
        self._direction = direction
        goal = self.maximum if direction > 0 else self.minimum
        self.bus.set_goal(goal, servo_id=self.servo_id)
```

Holding a key sends **one** packet: the travel limit in that direction. The
servo cruises there under its own speed control. Nothing re-commands while it
travels. Position is read every 100 ms for display only — never fed back into a
goal.

Stopping aims ahead of the current position so it decelerates forward into the
goal rather than reversing into it:

```python
def _lead(self) -> int:
    accel = max(1, self.acc) * 100          # acc register is 100 ticks/s^2
    braking = self.speed**2 / (2 * accel)
    latency = self.speed * 0.02
    return int(braking + latency)
```

### Autonomous mode

Idle motion issues one SYNC_WRITE per behaviour step, averaging **1.19 packets
per behaviour**, with 2–8 second holds between. Each step carries its own speed
and acceleration:

```python
Step(goals, speed=random.randint(520, 780), acc=45, dwell=random.uniform(2.2, 5.0))
```

Speeds range 300–1250, accelerations 15 (slow scan) to 90 (nod). During holds
torque is cut entirely, restored on the next move.

## What has been tried

| Change | Effect |
| --- | --- |
| Matched commanded speed to the goal advance rate | Improved, not fixed |
| One goal per direction change instead of 50/s | Improved, not fixed |
| Per-move acceleration (15–90) rather than flat 50 | Marginal |
| Raised speed (312 → 900–1200 ticks/s) | Marginal |
| Cut torque when stationary | Removes hold buzz, motion still rough |
| `P` 32 → 24, dead zone 1 → 4 | Marginal |
| `punch` 16 → 0 | Applied late; effect unconfirmed |

Current EEPROM state on axis 1: `P=24, I=0, D=32, punch=0, dead zone 4/4`,
angle limits written to 637/3711 (addresses 9 and 11).

## Measurements

- **Voltage at the servo: 12.2 V, flat.** But this was sampled while the servo
  was stationary and unloaded — position never changed, load read 0. **There is
  still no measurement under load**, which we consider the largest gap.
- No latched faults observed, though again only at idle.
- Position repeatability across sweeps is good: commanded 3711 reaches
  3694–3706 consistently, commanded 637 reaches 640–647.

A measurement tool exists but its output has not yet been captured:

```bash
python -m mio_core_services.firmware.jitter_test --id 1
```

It holds a position and samples it for 6 s with torque on, then 6 s with torque
off, reporting peak-to-peak and RMS in ticks.

## Specific questions

1. Is discarding the ACK after every write (`reset_input_buffer()` immediately
   after `flush()`) likely to leave the ESP32 forwarder or the servo bus in a
   state that degrades subsequent traffic? Should we read and validate status
   packets instead?

2. Does a broadcast SYNC_WRITE behave differently through a transparent ESP32
   forwarder than a direct 1 Mbps connection — particularly regarding the
   half-duplex turnaround?

3. The jitter is **sector-dependent** across the yaw travel. With a magnetic
   encoder, does that point at magnet decentring, or is it more likely varying
   mechanical load and backlash?

4. Are `P=24, D=32, I=0` with dead zone 4 sensible for a servo holding an
   off-axis mass, or should `D` be raised substantially?

5. Is 115200 on the host side a meaningful constraint? The servo bus runs at
   1 Mbps but every packet is gated by the slower hop.

## Reproducing

```bash
git clone <repo> && cd mio-core-services
uv sync
uv run python -m mio_core_services.firmware.scan_servos
uv run python -m mio_core_services.firmware.jitter_test --id 1
uv run python -m mio_core_services.firmware.system_teleop   # arrow keys
uv run python -m mio_core_services.firmware.idle_motion
```

Relevant source: `mio_core_services/firmware/sts3215.py` (protocol),
`jog.py` (velocity jogging), `idle_motion.py` (autonomous behaviour),
`tune_servo.py` (PID and dead-zone registers).
