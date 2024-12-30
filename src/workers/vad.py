import logging

from silero_vad import load_silero_vad

from tracks.vad_info import VADInfoTrack

from .base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class VADWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.vad_model = load_silero_vad(onnx=False)

    async def on_chunk(self, speech_prob):
        """
        Called by VAD track when a new audio chunk from WebRTC is processed
        """
        await self.emit("on_vad_data", {"speech_prob": round(speech_prob, 3)})

    async def on_start(self):
        await self.emit("on_vad_start", {})

    async def on_end(self):
        await self.emit("on_vad_end", {})

    def create_track(self, track):
        return VADInfoTrack(track, self.vad_model, self.on_chunk, self.on_start, self.on_end)

    def stop(self):
        super().stop()
        self._vad_model.reset_states()
