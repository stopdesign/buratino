import asyncio
import logging
from datetime import datetime
from io import BytesIO

import torchaudio
from silero_vad import VADIterator, load_silero_vad
from torchaudio.transforms import Resample

from .base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SAMPLING_RATE = 16000
FRAMES_PER_CHUNK = 512
VAD_THRESHOLD = 0.5
DT = "%H:%M:%S.%f"


def load_webm_to_pcm(webm_data, sampling_rate=16000):
    """
    Decode WebM audio data to a PCM tensor with
    a specified sample rate using torchaudio.load.
    """
    with BytesIO(webm_data) as webm_file:
        # Decode the WebM audio
        waveform, orig_sr = torchaudio.load(webm_file)

        if orig_sr != sampling_rate:
            resampler = Resample(orig_freq=orig_sr, new_freq=sampling_rate)
            waveform = resampler(waveform)

        return waveform, sampling_rate


class VADWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.header = b""
        self.event_types = ["audio_chunk"]
        self._vad_model = load_silero_vad()
        self._speech_active = False
        self.vad_iterator = VADIterator(self._vad_model, sampling_rate=SAMPLING_RATE)

    def reset(self):
        self.header = b""
        self._vad_model.reset_states()

    async def process(self, data):
        if not self.header:
            self.header = data
        else:
            data = self.header + data
            waveform, sr = load_webm_to_pcm(data)
            predicts = self._vad_model.audio_forward(waveform, sr=sr)

            if (predicts > VAD_THRESHOLD).any():
                dt = datetime.now()
                info = ", ".join(f"{a:.02f}" for a in predicts[0].tolist())
                logger.info(f"[{dt:{DT}}] 󱦉 VAD speach detected")  # 󱦉
                await self.emit(
                    "vad_speech_detected",
                    {"status": "speech_detected", "info": info},
                )

    async def handle_custom_message(self, message):
        pass

    async def run_forever(self):
        """Run the VAD worker."""
        while self._running:
            await asyncio.sleep(0.1)
