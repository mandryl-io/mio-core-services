import asyncio
import fractions
import json
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pyaudio
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import AudioStreamTrack, MediaStreamError
from av import AudioFrame, AudioResampler
from pywebrtc_audio import AudioProcessor

from mio_core_services.pipeline import MioPipeline

BASE = "http://localhost:7860"
SAMPLE_RATE = 48000
FRAME_SAMPLES = SAMPLE_RATE // 50  # 20ms

_executor = ThreadPoolExecutor(max_workers=2)

class MioClient:
    def __init__(self, 
        pipeline: MioPipeline = None,
        base_url: str = None,
    ) -> None:
        if (pipeline is None) == (base_url is None):
            raise ValueError("Exactly one of pipeline or base_url must be provided")
        self._pipeline = pipeline
        self._base_url = base_url
        self._pc = RTCPeerConnection()
    
    async def connect(self) -> None:
        if self._pipeline is not None:
            await self._pipeline.run_async()
        else:
            async with httpx.AsyncClient(timeout=120.0) as http:
                start = (
                    await http.post(
                        f"{self._base_url}/start",
                        json={"transport": "webrtc", "enableDefaultIceServers": True},
                    )
                ).json()
                offer_url = f"{self._base_url}/sessions/{start['sessionId']}/api/offer"

                offer = await self._pc.createOffer()
                await self._pc.setLocalDescription(offer)
                print("Sending offer (first connect can take a while while models load)...")
                answer = (
                    await http.post(
                        offer_url,
                        json={"sdp": self._pc.localDescription.sdp, "type": self._pc.localDescription.type},
                    )
                ).json()


class _FarEnd:
    """Speaker PCM that AEC subtracts from the mic (same role as the browser)."""

    def __init__(self, maxlen: int) -> None:
        self._samples: deque[int] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, pcm: np.ndarray) -> None:
        with self._lock:
            self._samples.extend(np.ascontiguousarray(pcm, dtype=np.int16).reshape(-1))

    def pull(self, n: int) -> np.ndarray:
        out = np.zeros(n, dtype=np.int16)
        with self._lock:
            have = min(n, len(self._samples))
            for i in range(have):
                out[i] = self._samples.popleft()
        return out


class MicrophoneTrack(AudioStreamTrack):
    def __init__(
        self, pa: pyaudio.PyAudio, processor: AudioProcessor, far_end: _FarEnd
    ) -> None:
        super().__init__()
        self._processor = processor
        self._far_end = far_end
        self._stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SAMPLES,
        )

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        if hasattr(self, "_timestamp"):
            self._timestamp += FRAME_SAMPLES
            wait = self._start + (self._timestamp / SAMPLE_RATE) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        else:
            self._start = time.time()
            self._timestamp = 0

        loop = asyncio.get_running_loop()
        pcm = await loop.run_in_executor(
            _executor,
            lambda: self._stream.read(FRAME_SAMPLES, exception_on_overflow=False),
        )
        near = np.frombuffer(pcm, dtype=np.int16)
        clean = self._processor.process(near, self._far_end.pull(len(near)))
        frame = AudioFrame.from_ndarray(
            clean.reshape(1, -1),
            format="s16",
            layout="mono",
        )
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        return frame

    def stop(self) -> None:
        if self._stream.is_active():
            self._stream.stop_stream()
            self._stream.close()
        super().stop()


async def _play_audio(track, pa: pyaudio.PyAudio, far_end: _FarEnd) -> None:
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        output=True,
        frames_per_buffer=FRAME_SAMPLES,
    )
    resampler = AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    loop = asyncio.get_running_loop()
    heard = False
    try:
        while True:
            frame = await track.recv()
            for out in resampler.resample(frame):
                samples = np.ascontiguousarray(out.to_ndarray()).reshape(-1)
                far_end.push(samples)
                pcm = samples.tobytes()
                if not heard and any(pcm):
                    heard = True
                    print("Playing bot audio")
                await loop.run_in_executor(_executor, stream.write, pcm)
    except MediaStreamError:
        pass
    finally:
        stream.stop_stream()
        stream.close()


async def connect() -> None:
    pa = pyaudio.PyAudio()
    far_end = _FarEnd(maxlen=SAMPLE_RATE)
    processor = AudioProcessor(
        sample_rate=SAMPLE_RATE,
        echo_cancellation=True,
        noise_suppression=True,
        auto_gain_control=True,
        stream_delay_ms=80,
    )
    pc = RTCPeerConnection()
    mic = MicrophoneTrack(pa, processor, far_end)
    pc.addTrack(mic)
    channel = pc.createDataChannel("chat")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        print(f"WebRTC {pc.connectionState}")

    @pc.on("track")
    def on_track(track) -> None:
        print(f"Receiving {track.kind} track")
        if track.kind == "audio":
            asyncio.ensure_future(_play_audio(track, pa, far_end))

    @channel.on("open")
    def on_channel_open() -> None:
        channel.send(
            json.dumps(
                {
                    "type": "signalling",
                    "message": {
                        "type": "trackStatus",
                        "receiver_index": 0,
                        "enabled": True,
                    },
                }
            )
        )

    async with httpx.AsyncClient(timeout=120.0) as http:
        start = (
            await http.post(
                f"{BASE}/start",
                json={"transport": "webrtc", "enableDefaultIceServers": True},
            )
        ).json()
        offer_url = f"{BASE}/sessions/{start['sessionId']}/api/offer"

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        print("Sending offer (first connect can take a while while models load)...")
        answer = (
            await http.post(
                offer_url,
                json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            )
        ).json()
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )
        await http.patch(offer_url, json={"pc_id": answer["pc_id"], "candidates": []})

    print("Speak into the mic (Ctrl+C to quit)")
    try:
        await asyncio.Future()
    finally:
        mic.stop()
        await pc.close()
        pa.terminate()


if __name__ == "__main__":
    try:
        asyncio.run(connect())
    except KeyboardInterrupt:
        pass
