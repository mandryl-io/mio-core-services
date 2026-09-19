"""Boot entry: if WiFi is already up, exit; otherwise host setup until it is.

Started first by `mio-wifi.service` so the head, eyes, and conversation wait.
While the setup hotspot is up the eyes fade slowly on and off.
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Callable
from pathlib import Path

from mio_core_services.constants import (
    WIFI_CONNECT_WAIT,
    WIFI_DEVICE,
    WIFI_FADE_JOIN_TIMEOUT,
    WIFI_FADE_PERIOD,
    WIFI_HOTSPOT_RETRY,
    WIFI_RETRY_SLEEP,
    WIFI_SETUP_POLL,
    WIFI_SETUP_PORT,
)
from mio_core_services.lighting.eyes import (
    DEFAULT_LEFT_PIN,
    DEFAULT_RIGHT_PIN,
    Stopping,
    try_open_eyes,
)
from mio_core_services.wifi.fade import run_fade
from mio_core_services.wifi.nmcli import Radio, RadioError
from mio_core_services.wifi.server import DEFAULT_APP_DIR, SetupState, serve


def run_in_thread(fn: Callable, *args, name: str | None = None) -> threading.Thread:
    thread = threading.Thread(target=fn, args=args, name=name, daemon=True)
    thread.start()
    return thread


def wait_for_home(radio: Radio, seconds: float, stopping: Stopping) -> bool:
    deadline = time.monotonic() + seconds
    while not stopping.requested:
        if radio.is_home_connected():
            return True
        if time.monotonic() >= deadline:
            return False
        _sleep(WIFI_RETRY_SLEEP, stopping)
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
            _sleep(WIFI_HOTSPOT_RETRY, stopping)
    return False


def run_setup(radio: Radio, stopping: Stopping, eyes, port: int, app_dir: Path,
              connect_wait: float):
    """Wait for home WiFi, or host the setup hotspot until one is chosen."""
    radio.wifi_on()
    print("Checking for an existing WiFi connection.", flush=True)
    if wait_for_home(radio, connect_wait, stopping):
        print(f"Already on {radio.active_ssid() or 'WiFi'}.", flush=True)
        return None, None
    if stopping.requested:
        return None, None
    if not _start_hotspot(radio, stopping):
        return None, None
    fade_thread = None
    if eyes is not None:
        fade_thread = run_in_thread(
            run_fade, eyes, stopping, WIFI_FADE_PERIOD, name="wifi-fade"
        )
        print("Eyes fading until a home network is chosen.", flush=True)
    state = SetupState(radio)
    http = serve(state, port=port, app_dir=app_dir)
    print(
        f"Setup page at http://0.0.0.0:{http.server_address[1]}/ — "
        "waiting for a network.",
        flush=True,
    )
    while not stopping.requested and not state.done.is_set():
        if radio.is_home_connected():
            state.done.set()
            break
        _sleep(WIFI_SETUP_POLL, stopping)
    if state.done.is_set():
        print(f"Joined {radio.active_ssid() or 'WiFi'}.", flush=True)
    return fade_thread, http


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=WIFI_DEVICE)
    parser.add_argument("--port", type=int, default=WIFI_SETUP_PORT)
    parser.add_argument("--app-dir", default=str(DEFAULT_APP_DIR))
    parser.add_argument("--connect-wait", type=float, default=WIFI_CONNECT_WAIT,
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
    fade_thread = None
    http = None

    try:
        fade_thread, http = run_setup(
            radio, stopping, eyes, args.port, Path(args.app_dir), args.connect_wait
        )
    finally:
        stopping.requested = True
        if http is not None:
            http.shutdown()
        if fade_thread is not None:
            fade_thread.join(timeout=WIFI_FADE_JOIN_TIMEOUT)
            if fade_thread.is_alive():
                print(
                    "Fade thread did not stop in time; releasing the eye pins anyway.",
                    flush=True,
                )
        if eyes is not None:
            eyes.off()
            eyes.close()
            print("Eyes off; pins released.", flush=True)


if __name__ == "__main__":
    main()
