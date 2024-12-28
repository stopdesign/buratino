import asyncio
import logging
from time import monotonic

from aiortc import AudioStreamTrack
from aiortc.mediastreams import AudioFrame

logger = logging.getLogger(__name__)


class TTSTrack(AudioStreamTrack):
    def __init__(self, get_audio_packet):
        super().__init__()
        self.stream_time = None
        self.get_audio_packet = get_audio_packet

    async def recv(self) -> AudioFrame:
        packet, duration = self.get_audio_packet()

        if self.stream_time is None:
            self.stream_time = monotonic()

        wait = self.stream_time - monotonic()
        await asyncio.sleep(wait)

        self.stream_time += duration
        return packet
