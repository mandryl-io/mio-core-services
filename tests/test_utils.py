from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transports.base_transport import BaseTransport

class MockTransport(BaseTransport):
    def __init__(self):
        super().__init__()
        self._in = FrameProcessor()
        self._out = FrameProcessor()

    def input(self) -> FrameProcessor:
        return self._in

    def output(self) -> FrameProcessor:
        return self._out
