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
        self.vad_model = load_silero_vad(onnx=False)

    async def on_vad_data(self, speech_prob):
        """
        Called by VAD track when a new audio chunk from WebRTC is processed
        """
        await self.emit("on_vad_data", {"speech_prob": round(speech_prob, 3)})

    def create_track(self, track):
        vt = VADInfoTrack(track, self.vad_model, self.on_vad_data)
        return vt

    def stop(self):
        super().stop()
        self._vad_model.reset_states()
