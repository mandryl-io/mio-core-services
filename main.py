import asyncio
import sys

from pipecat.evals.transport import EvalTransportParams
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.local.audio import (
    LocalAudioTransport,
    LocalAudioTransportParams,
)

from mio_core_services.pipeline import MioPipeline, MioPipelineConfig
from mio_core_services.vector_store.chroma import ChromaVectorStore
from mio_core_services.vector_store.embeddings import SentenceTransformerEmbedder

SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. Keep replies brief and conversational."
)
MIO_CHROMA_PATH = "./mio-chroma"


async def _run_pipeline(transport: BaseTransport) -> None:
    pipeline_config = MioPipelineConfig(
        llm_model="gemma4",
        system_instruction=SYSTEM_INSTRUCTION,
        transport=transport,
        vector_store=ChromaVectorStore(
            path=MIO_CHROMA_PATH,
            embedder=SentenceTransformerEmbedder(),
        ),
    )
    await MioPipeline(pipeline_config).run_async()


async def bot(runner_args: RunnerArguments) -> None:
    """Pipecat runner entrypoint (e.g. uv run main.py -t eval)."""
    transport_params = {
        "eval": lambda: EvalTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }
    transport = await create_transport(runner_args, transport_params)
    await _run_pipeline(transport)


async def main() -> None:
    """Interactive local mic/speakers when no -t transport is selected."""
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )
    await _run_pipeline(transport)


if __name__ == "__main__":
    if "-t" in sys.argv or "--transport" in sys.argv:
        from pipecat.runner.run import main as runner_main

        runner_main()
    else:
        asyncio.run(main())
