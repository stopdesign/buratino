import logging
from statistics import mean

import torch
from aiortc import AudioStreamTrack
from av import AudioFrame, AudioResampler

logger = logging.getLogger("pc")
logger.setLevel(logging.INFO)


class VADInfoTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(self, track, vad_model, callback):
        super().__init__()
        self.track = track
        self.callback = callback

        self.vad_model = vad_model

        self.sampling_rate = 16_000
        self.chunk_size = 512

        self.resampler = AudioResampler(format="s16", layout="mono", rate=self.sampling_rate)
        self.buffer = torch.tensor([], dtype=torch.float32)

        self.segments = []
        self.segments_amount = 80
        self.is_activated = False
        self.is_activated_threshhold = 5  # how many samples needed for activation
        self.is_activated_amount = 0

    async def recv(self) -> AudioFrame:
        frame: AudioFrame = await self.track.recv()

        # Resample to 16k
        frame_16 = self.resampler.resample(frame)[0]
        frame_array = torch.tensor(frame_16.to_ndarray()[0], dtype=torch.float32) / 32_767

        self.buffer = torch.cat([self.buffer, frame_array])

        speech_prob = 0.0

        if self.buffer.size(0) >= self.chunk_size:
            # process and remove first samples
            chunk = self.buffer[: self.chunk_size]
            speech_prob = self.vad_model(chunk, self.sampling_rate).item()
            self.buffer = self.buffer[self.chunk_size :]

            await self.callback(speech_prob)

        is_speech = speech_prob >= 0.4

        if is_speech:
            # print(f"Speech_prob={speech_prob:0.03f}")
            self.is_activated_amount += 1
            if self.is_activated_amount >= self.is_activated_threshhold and not self.is_activated:
                self.is_activated = True
                logger.info("VAD activated")
                self.segments = []

        self.segments.append(int(is_speech))
        self.segments = self.segments[-self.segments_amount :]

        # last 80 segments was no speach
        if (
            mean(self.segments) <= 0.4
            and self.is_activated
            and len(self.segments) >= self.segments_amount
        ):
            logger.info("Let's Speech to text!")
            self.is_activated_amount = 0
            self.is_activated = False
            self.segments = []

        return frame
