"""Tiny HTTP API the phone talks to while joined to the setup hotspot."""

from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from mio_core_services.wifi.nmcli import Radio, RadioError, parse_connect_body

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP_DIR = REPO_ROOT / "app"
JOIN_WAIT = 15.0
JOIN_POLL = 1.0


class SetupState:
    """Shared between the HTTP handlers and the boot loop."""

    def __init__(self, radio: Radio) -> None:
        self.radio = radio
        self.mode = "setup"
        self.target_ssid: str | None = None
        self.last_error: str | None = None
        self.done = threading.Event()
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            ssid = self.target_ssid
            mode = self.mode
            error = self.last_error
        if mode == "setup" and ssid is None:
            ssid = self.radio.hotspot_ssid
        elif mode == "connected" and ssid is None:
            ssid = self.radio.active_ssid()
        payload = {"mode": mode, "ssid": ssid}
        if error:
            payload["error"] = error
        return payload

    def request_join(self, ssid: str, password: str) -> dict:
        with self._lock:
            if self.mode == "joining":
                return {
                    "ok": False,
                    "error": "Already joining a network. Wait a moment.",
                }
            self.mode = "joining"
            self.target_ssid = ssid
            self.last_error = None
        return {
            "ok": True,
            "mode": "joining",
            "ssid": ssid,
            "message": "Joining that network. The setup WiFi will close when it works.",
        }

    def start_join(self, ssid: str, password: str) -> None:
        thread = threading.Thread(
            target=self._join, args=(ssid, password), name="wifi-join", daemon=True
        )
        thread.start()

    def _join(self, ssid: str, password: str) -> None:
        try:
            self.radio.join(ssid, password)
            deadline = time.monotonic() + JOIN_WAIT
            while time.monotonic() < deadline:
                if self.radio.is_home_connected():
                    with self._lock:
                        self.mode = "connected"
                        self.target_ssid = ssid
                        self.last_error = None
                    self.done.set()
                    return
                time.sleep(JOIN_POLL)
            raise RadioError("Joined, but the Pi has no address yet.")
        except RadioError as exc:
            try:
                self.radio.start_hotspot()
            except RadioError:
                pass
            with self._lock:
                self.mode = "setup"
                self.last_error = str(exc) or "Could not join that network."


class SetupHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, state: SetupState, app_dir: Path) -> None:
        self.state = state
        self.app_dir = app_dir.resolve()
        super().__init__(address, SetupHandler)


class SetupHandler(BaseHTTPRequestHandler):
    server: SetupHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        print(f"wifi-setup: {args[0]}", flush=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/status":
            self._send_json(200, self.server.state.snapshot())
            return
        if path == "/api/networks":
            self._send_networks()
            return
        self._send_app(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if unquote(parsed.path) != "/api/connect":
            self._send_json(404, {"ok": False, "error": "Not found."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Send a JSON object.")
            ssid, password = parse_connect_body(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            message = str(exc) if str(exc) else "Could not read that request."
            self._send_json(400, {"ok": False, "error": message})
            return
        result = self.server.state.request_join(ssid, password)
        code = 200 if result.get("ok") else 409
        self._send_json(code, result)
        if result.get("ok"):
            self.server.state.start_join(ssid, password)

    def _send_networks(self) -> None:
        try:
            networks = [
                {"ssid": net.ssid, "signal": net.signal, "security": net.security}
                for net in self.server.state.radio.scan()
            ]
        except RadioError as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {"networks": networks})

    def _send_app(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        candidate = (self.server.app_dir / relative).resolve()
        try:
            candidate.relative_to(self.server.app_dir)
        except ValueError:
            self._send_json(403, {"ok": False, "error": "Not found."})
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            self.send_error(404, "Not found")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


def serve(state: SetupState, host: str = "0.0.0.0", port: int = 80,
          app_dir: Path | str = DEFAULT_APP_DIR) -> SetupHTTPServer:
    server = SetupHTTPServer((host, port), state, Path(app_dir))
    thread = threading.Thread(target=server.serve_forever, name="wifi-http", daemon=True)
    thread.start()
    return server
