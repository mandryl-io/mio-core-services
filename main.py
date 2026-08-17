from pipecat.evals.transport import EvalTransportParams
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport, TransportParams

from mio_core_services.constants import DEFAULT_MIO_CHROMA_PATH, DEFAULT_SYSTEM_INSTRUCTION
from mio_core_services.pipeline import MioPipeline, MioPipelineConfig
from mio_core_services.memory.backends.chroma import ChromaVectorStore
from mio_core_services.memory.embeddings import SentenceTransformerEmbedder


async def _run_pipeline(transport: BaseTransport) -> None:
    pipeline_config = MioPipelineConfig(
        llm_model="gemma4",
        system_instruction=DEFAULT_SYSTEM_INSTRUCTION,
        transport=transport,
        vector_store=ChromaVectorStore(
            path=DEFAULT_MIO_CHROMA_PATH,
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
