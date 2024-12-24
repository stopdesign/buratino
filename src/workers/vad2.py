import asyncio
import logging

from silero_vad import load_silero_vad

from tracks.vad_info import VADInfoTrack

from .base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class VADWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.event_types = ["audio_chunk"]
        self.speech_active = False
        self.vad_track = None
        self.vad_model = load_silero_vad(onnx=True)

    async def on_vad_data(self, speech_prob):
        # print("ON VAD DATA", speech_prob)
        await self.emit("on_vad_data", {"speech_prob": round(speech_prob, 3)})

    def create_vad_track(self, track):
        vt = VADInfoTrack(track, self.vad_model, self.on_vad_data)
        return vt

    def reset(self):
        self._vad_model.reset_states()

    # async def run_forever(self):
    #     """Run the VAD worker."""
    #     while self._running:
    #         await asyncio.sleep(0.1)
