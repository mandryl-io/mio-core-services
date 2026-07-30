import asyncio
import sys
from pathlib import Path

from pipecat.transports.local.audio import (
    LocalAudioTransport,
    LocalAudioTransportParams,
)

sys.path.insert(0, str(Path(__file__).resolve().parent / "mio-core-services"))

from services.pipeline import MioPipeline


async def main() -> None:
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )
    await MioPipeline(transport).run_async()


if __name__ == "__main__":
    asyncio.run(main())
