"""Local HTTP app that walks firmware workflows."""

from __future__ import annotations

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from devtools.firmware_lab.catalog import catalog_payload, get_tool, get_workflow
from devtools.firmware_lab.commands import argv_for_step, build_argv
from devtools.firmware_lab.runner import RunResult, run_tool

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("JSON body must be an object")
    return payload


class FirmwareLabHandler(BaseHTTPRequestHandler):
    server_version = "MioFirmwareLab/0.1"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[firmware-lab] {self.address_string()} {format % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_static(self, relative: str) -> None:
        path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR not in path.parents and path != STATIC_DIR:
            self._send_json(403, {"error": "Forbidden"})
            return
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            self._send_json(404, {"error": "Not found"})
            return
        suffix = path.suffix.lower()
        types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        self._send(200, path.read_bytes(), types.get(suffix, "application/octet-stream"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_static("index.html")
            return
        if parsed.path == "/api/catalog":
            self._send_json(200, catalog_payload())
            return
        if parsed.path.startswith("/"):
            self._send_static(parsed.path.lstrip("/"))
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = _json_body(self)
        except (ValueError, TypeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        values = payload.get("values") or {}
        if not isinstance(values, dict):
            self._send_json(400, {"error": "values must be an object"})
            return
        try:
            if parsed.path == "/api/command":
                self._send_json(200, _command_response(payload, values))
                return
            if parsed.path == "/api/run":
                self._send_json(200, _run_response(payload, values))
                return
        except KeyError as exc:
            self._send_json(404, {"error": str(exc)})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except subprocess.TimeoutExpired:
            self._send_json(504, {"error": "Firmware command timed out"})
            return
        self._send_json(404, {"error": "Not found"})


def _command_response(payload: dict, values: dict) -> dict:
    if "step_id" in payload:
        workflow = get_workflow(str(payload.get("workflow_id", "")))
        argv = argv_for_step(workflow, str(payload["step_id"]), values)
        step = next(item for item in workflow.steps if item.id == payload["step_id"])
        tool = get_tool(step.tool)
    else:
        tool = get_tool(str(payload.get("tool_id", "")))
        argv = build_argv(tool, values)
    return {
        "argv": argv,
        "command": " ".join(argv),
        "tool": tool.id,
        "needs_tty": tool.needs_tty,
        "moves_hardware": tool.moves_hardware,
        "notes": tool.notes,
    }


def _run_payload(result: RunResult) -> dict:
    return {
        "argv": result.argv,
        "command": " ".join(result.argv),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
    }


def _run_response(payload: dict, values: dict) -> dict:
    confirm = bool(payload.get("confirm"))
    timeout = float(payload.get("timeout") or 120)
    if "step_id" in payload:
        workflow = get_workflow(str(payload.get("workflow_id", "")))
        step = next(
            (item for item in workflow.steps if item.id == payload["step_id"]),
            None,
        )
        if step is None:
            raise KeyError(f"Unknown step {payload['step_id']!r}")
        from devtools.firmware_lab.commands import step_values

        tool = get_tool(step.tool)
        result = run_tool(tool, step_values(workflow, step, values), confirm=confirm, timeout=timeout)
        return _run_payload(result)
    tool = get_tool(str(payload.get("tool_id", "")))
    return _run_payload(run_tool(tool, values, confirm=confirm, timeout=timeout))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FirmwareLabHandler)
    print(f"Firmware lab at http://{args.host}:{args.port}/")
    print("TTY tools print a command to paste into ssh -t; they are not launched from the browser.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
