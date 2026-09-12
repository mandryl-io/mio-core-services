import asyncio
import os

from pipecat.runner import run as runner
from pipecat.runner.types import RunnerArguments

from mio_core_services.constants import (
    DEFAULT_FACE_CHROMA_PATH,
    DEFAULT_MEDICATION_DB_PATH,
    DEFAULT_MIO_CHROMA_PATH,
)
from mio_core_services.memory import MioVectorStore
from mio_core_services.perception.local_face import create_face_backend
from mio_core_services.perception.store import FaceStore
from mio_core_services.pipeline import MioPipeline, MioPipelineConfig

_vector_store = None
_face_store = None
_face_backend = None


def _shared_resources():
    """Load stores and InsightFace once. Safe to call again."""
    global _vector_store, _face_store, _face_backend
    if _vector_store is None:
        _vector_store = MioVectorStore.load(store_name=DEFAULT_MIO_CHROMA_PATH)
        _face_store = FaceStore(path=DEFAULT_FACE_CHROMA_PATH)
        _face_backend = create_face_backend()
    return _vector_store, _face_store, _face_backend


async def bot(runner_args: RunnerArguments) -> None:
    """Pipecat runner entrypoint. WebRTC is the default; use `-t eval` for evals."""
    # Offer/answer already ran; keep the event loop free so ICE can finish
    # while any first-time model load happens in a worker thread.
    vector_store, face_store, face_backend = await asyncio.to_thread(_shared_resources)
    config = MioPipelineConfig(
        vector_store=vector_store,
        reminder_db_path=DEFAULT_MEDICATION_DB_PATH,
        face_store=face_store,
        face_backend=face_backend,
    )
    await MioPipeline(config).run_async(runner_args)


if __name__ == "__main__":
    if os.getenv("PIPECAT_HEADLESS"):
        runner._setup_frontend_routes = lambda _app: None
    _shared_resources()
    runner.main()
