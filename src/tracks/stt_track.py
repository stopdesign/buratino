import asyncio
import logging

from aiortc import AudioStreamTrack
from av import AudioFrame

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class STTTrack(AudioStreamTrack):
    def __init__(self, track, callback):
        super().__init__()
        self.track = track
        self.callback = callback

        self.buffer = bytearray()
        self.segments_amount = 10
        self.segment_size = None
        self.lock = asyncio.Lock()

    async def recv(self) -> AudioFrame:
        frame: AudioFrame = await self.track.recv()

        segment = frame.to_ndarray()[0].tobytes()

        # Determine segment size dynamically if not already done
        if self.segment_size is None:
            self.segment_size = len(segment)

        self.buffer.extend(segment)

        if (
            len(self.buffer) >= (self.segment_size * self.segments_amount)
            or len(segment) < self.segment_size
        ):
            await self.callback(self.buffer)
            self.buffer.clear()

        return frame
