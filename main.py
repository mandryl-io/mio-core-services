import os

from pipecat.runner import run as runner
from pipecat.runner.types import RunnerArguments

from mio_core_services.constants import DEFAULT_MIO_CHROMA_PATH
from mio_core_services.memory import MioVectorStore
from mio_core_services.pipeline import MioPipeline, MioPipelineConfig


async def bot(runner_args: RunnerArguments) -> None:
    """Pipecat runner entrypoint. WebRTC is the default; use `-t eval` for evals."""
    config = MioPipelineConfig(
        vector_store=MioVectorStore.load(store_name=DEFAULT_MIO_CHROMA_PATH),
    )
    await MioPipeline(config).run_async(runner_args)


if __name__ == "__main__":
    if os.getenv("PIPECAT_HEADLESS"):
        runner._setup_frontend_routes = lambda _app: None
    runner.main()
