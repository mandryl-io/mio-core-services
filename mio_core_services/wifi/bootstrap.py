"""Boot entry: if WiFi is already up, exit; otherwise host setup until it is.

Started first by `mio-wifi.service` so the head, eyes, and conversation wait.
While the setup hotspot is up the eyes fade slowly on and off.
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

from mio_core_services.lighting.eyes import (
    DEFAULT_LEFT_PIN,
    DEFAULT_RIGHT_PIN,
    Stopping,
    open_eyes,
)
from mio_core_services.wifi import SETUP_PORT, WIFI_DEVICE
from mio_core_services.wifi.fade import FADE_PERIOD, run_fade
from mio_core_services.wifi.nmcli import Radio, RadioError
from mio_core_services.wifi.server import DEFAULT_APP_DIR, SetupState, serve

CONNECT_WAIT = 20.0
RETRY_SLEEP = 2.0
HOTSPOT_RETRY = 3.0


def try_open_eyes(left_pin: int, right_pin: int, active_low: bool):
    try:
        return open_eyes(left_pin, right_pin, active_low)
    except SystemExit as exc:
        print(f"Eyes unavailable ({exc}). Setup continues without them.", flush=True)
        return None


def wait_for_home(radio: Radio, seconds: float, stopping: Stopping) -> bool:
    deadline = time.monotonic() + seconds
    while not stopping.requested:
        if radio.is_home_connected():
            return True
        if time.monotonic() >= deadline:
            return False
        _sleep(RETRY_SLEEP, stopping)
    return False


def _sleep(seconds: float, stopping: Stopping) -> None:
    deadline = time.monotonic() + seconds
    while not stopping.requested:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.05, left))


def _start_hotspot(radio: Radio, stopping: Stopping) -> bool:
    while not stopping.requested:
        try:
            radio.start_hotspot()
            print(
                f"Setup hotspot {radio.hotspot_ssid} "
                f"(password {radio.hotspot_password}) on {radio.device}.",
                flush=True,
            )
            return True
        except RadioError as exc:
            print(f"Could not start hotspot ({exc}); retrying.", flush=True)
            _sleep(HOTSPOT_RETRY, stopping)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=WIFI_DEVICE)
    parser.add_argument("--port", type=int, default=SETUP_PORT)
    parser.add_argument("--app-dir", default=str(DEFAULT_APP_DIR))
    parser.add_argument("--connect-wait", type=float, default=CONNECT_WAIT,
                        help="Seconds to wait for an existing WiFi lease at boot.")
    parser.add_argument("--left-pin", type=int, default=DEFAULT_LEFT_PIN)
    parser.add_argument("--right-pin", type=int, default=DEFAULT_RIGHT_PIN)
    parser.add_argument("--active-low", action="store_true")
    parser.add_argument("--no-eyes", action="store_true",
                        help="Skip the lamps (useful off the Pi).")
    args = parser.parse_args()

    radio = Radio(device=args.device)
    stopping = Stopping()
    eyes = None if args.no_eyes else try_open_eyes(
        args.left_pin, args.right_pin, args.active_low
    )
    fade_thread: threading.Thread | None = None
    http = None

    try:
        radio.wifi_on()
        print("Checking for an existing WiFi connection.", flush=True)
        if wait_for_home(radio, args.connect_wait, stopping):
            print(f"Already on {radio.active_ssid() or 'WiFi'}.", flush=True)
            return
        if stopping.requested:
            return
        if not _start_hotspot(radio, stopping):
            return
        if eyes is not None:
            fade_thread = threading.Thread(
                target=run_fade, args=(eyes, stopping, FADE_PERIOD), daemon=True
            )
            fade_thread.start()
            print("Eyes fading until a home network is chosen.", flush=True)
        state = SetupState(radio)
        http = serve(state, port=args.port, app_dir=Path(args.app_dir))
        print(
            f"Setup page at http://0.0.0.0:{http.server_address[1]}/ — "
            "waiting for a network.",
            flush=True,
        )
        while not stopping.requested and not state.done.is_set():
            if radio.is_home_connected():
                state.done.set()
                break
            _sleep(0.4, stopping)
        if state.done.is_set():
            print(f"Joined {radio.active_ssid() or 'WiFi'}.", flush=True)
    finally:
        stopping.requested = True
        if http is not None:
            http.shutdown()
        if fade_thread is not None:
            fade_thread.join(timeout=1.0)
        if eyes is not None:
            eyes.off()
            eyes.close()
            print("Eyes off; pins released.", flush=True)


if __name__ == "__main__":
    main()
