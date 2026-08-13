import pytest

from mio_core_services.pipeline import MioPipeline, MioPipelineConfig
from pipecat.transports.base_transport import BaseTransport
from tests.test_utils import MockTransport

"""
Things we might want to test:

1. Does the pipeline terminate gracefully if any of the models/services cannot start up properly
(e.g. vRAM usage is too high, or the model is not available)?

2. Does the pipeline terminate gracefully if the worker runner is not working properly?
"""


@pytest.fixture
async def pipeline(transport: BaseTransport) -> MioPipeline:
    return MioPipeline(transport)

async def test_pipeline_fails_with_invalid_service():
    """
    Tests that the pipeline fails if the LLM service cannot start up properly
    by passing an invalid service name to the pipeline config.
    """
    transport = MockTransport()
    pipeline_config = MioPipelineConfig(
        llm_model="foobar-invalid-model-name",
        system_instruction="You are a helpful voice assistant. Keep replies brief and conversational.",
        transport=transport,
    )
    pipeline = MioPipeline(pipeline_config)
    with pytest.raises(RuntimeError) as e:
        await pipeline.run_async()

def test_pipeline_gracefully_terminates_if_worker_runner_fails():
    pass
