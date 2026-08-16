from pipecat.evals.transport import EvalTransportParams
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport, TransportParams

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
    """Pipecat runner entrypoint (e.g. uv run main.py -t webrtc)."""
    transport_params = {
        "eval": lambda: EvalTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }
    transport = await create_transport(runner_args, transport_params)
    await _run_pipeline(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main as runner_main

    runner_main()
