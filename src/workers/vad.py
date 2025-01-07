import logging
from collections import deque

import numpy as np
from silero_vad import load_silero_vad

from tracks.vad_info import VADInfoTrack

from .base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class VADWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.vad_model = load_silero_vad(onnx=False)
        self.prob_buffer_window = 50
        self.prob_buffer = deque(maxlen=self.prob_buffer_window)

    def pause_duration(self, silence_threshold=0.5, window=10) -> float:
        """
        Calculate accumulated pause duration for a given VAD threshold and window.
        Could help calculate uncertainty level.
        """
        window = min(window, self.prob_buffer_window)

        # Not enough data, return
        if len(self.prob_buffer) < window / 2:
            return 0.0

        silence_ratio = np.mean(np.array(self.prob_buffer)[-window:] < silence_threshold)

        # Convert to seconds (20ms intervals)
        return silence_ratio

    def on_chunk(self, speech_prob):
        """
        Called by VAD track when a new audio chunk from WebRTC is processed.
        """
        self.prob_buffer.append(speech_prob)

        # for el in list(np.array(self.prob_buffer)[:10]):
        #     print(f"{el:0.2f} ", end="")
        # print()
        # for el in list(np.array(self.prob_buffer)):
        #     print(f"{el:0.2f} ", end="")
        # print()

        try:
            payload = {
                "speech_prob": round(speech_prob, 3),
                "mean_prob": float(np.mean(np.array(self.prob_buffer)[-5:])),
                "silence_ratio_short": float(self.pause_duration(0.05, 5)),
                "silence_ratio_long": float(self.pause_duration(0.05, 20)),
            }
            self.emit("on_vad_data", payload)
        except Exception as e:
            logger.exception(e)

    def on_start(self):
        self.emit("on_vad_start", {})

    def on_end(self):
        self.emit("on_vad_end", {})

    def create_track(self, track):
        return VADInfoTrack(track, self.vad_model, self.on_chunk, self.on_start, self.on_end)

    def stop(self):
        super().stop()
        self._vad_model.reset_states()
