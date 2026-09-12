"""OpenAI-compatible Kokoro TTS on localhost, for LiveKit openai.TTS."""

import argparse
import io
import json
import logging
import os
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_MODEL_NAME = "kokoro-v1.0.int8.onnx"
_VOICES_NAME = "voices-v1.0.bin"
_CACHE_DIR = Path.home() / ".cache" / "mio" / "kokoro-onnx"

_engine = None


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    logger.info("Downloading %s", url)
    request = urllib.request.Request(url, headers={"User-Agent": "mio-kokoro-server"})
    with urllib.request.urlopen(request) as response, tmp.open("wb") as handle:
        handle.write(response.read())
    tmp.replace(dest)
    return dest


def _load_engine():
    from kokoro_onnx import Kokoro

    model = _download(f"{_RELEASE}/{_MODEL_NAME}", _CACHE_DIR / _MODEL_NAME)
    voices = _download(f"{_RELEASE}/{_VOICES_NAME}", _CACHE_DIR / _VOICES_NAME)
    return Kokoro(str(model), str(voices))


def _lang_for_voice(voice: str) -> str:
    return {"bf": "en-gb", "bm": "en-gb"}.get(voice[:2], "en-us")


def _wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return buf.getvalue()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("", "/health", "/v1"):
            self._send(200, b"ok", "text/plain")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/audio/speech":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        text = (body.get("input") or "").strip()
        if not text:
            self.send_error(400, "input is required")
            return
        voice = body.get("voice") or "af_alloy"
        speed = float(body.get("speed") or 1.0)
        try:
            assert _engine is not None
            samples, rate = _engine.create(
                text, voice=voice, speed=speed, lang=_lang_for_voice(voice)
            )
        except Exception:
            logger.exception("Kokoro synthesis failed")
            self.send_error(500, "synthesis failed")
            return
        self._send(200, _wav_bytes(samples, rate), "audio/wav")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Local Kokoro TTS for LiveKit")
    parser.add_argument("--host", default=os.getenv("KOKORO_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("KOKORO_PORT", "8880")))
    args = parser.parse_args()

    global _engine
    logger.info("Loading Kokoro ONNX model")
    _engine = _load_engine()

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    logger.info("Kokoro TTS listening on http://%s:%s/v1", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
