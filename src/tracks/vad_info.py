import logging
from statistics import mean

import torch
from aiortc import AudioStreamTrack
from av import AudioFrame, AudioResampler

logger = logging.getLogger("pc")
logger.setLevel(logging.INFO)


# One audio chunk (30+ ms) takes less than 1ms to be processed on a single CPU thread.
# Using batching or GPU can also improve performance considerably.
# Under certain conditions ONNX may even run up to 4-5x faster.


class VADInfoTrack(AudioStreamTrack):
    def __init__(self, track, vad_model, on_chunk, on_start, on_end):
        super().__init__()
        self.track = track
        self.on_chunk = on_chunk
        self.on_start = on_start
        self.on_end = on_end

        self.vad_model = vad_model

        self.sampling_rate = 16_000
        self.chunk_size = 512

        self.resampler = AudioResampler(format="s16", layout="mono", rate=self.sampling_rate)
        self.buffer = torch.tensor([], dtype=torch.float32)

        self.segments = []
        self.segments_amount = 20

        self.is_activated = False
        self.is_activated_threshhold = 5  # how many samples needed for activation
        self.is_activated_amount = 0

    async def recv(self) -> AudioFrame:
        frame: AudioFrame = await self.track.recv()

        # Resample to 16_000 fps
        frame_16 = self.resampler.resample(frame)[0]
        # Convert to float32
        frame_array = torch.tensor(frame_16.to_ndarray()[0], dtype=torch.float32) / 32_767

        self.buffer = torch.cat([self.buffer, frame_array])

        speech_prob = 0.0

        if self.buffer.size(0) >= self.chunk_size:
            # process and remove first samples
            chunk = self.buffer[: self.chunk_size]
            speech_prob = self.vad_model(chunk, self.sampling_rate).item()
            self.buffer = self.buffer[self.chunk_size :]
            self.on_chunk(speech_prob)
        else:
            # not enough data for VAD
            return frame

        is_speech = speech_prob >= 0.2

        if is_speech:
            # print(f"Speech_prob={speech_prob:0.03f}")
            self.is_activated_amount += 1
            if self.is_activated_amount >= self.is_activated_threshhold and not self.is_activated:
                self.is_activated = True
                self.segments = []
                self.on_start()

        self.segments.append(int(is_speech))
        self.segments = self.segments[-self.segments_amount :]

        speech_ratio = mean(self.segments)

        # last N segments was no speech
        if self.is_activated and speech_ratio <= 0.1 and len(self.segments) >= self.segments_amount:
            self.is_activated_amount = 0
            self.is_activated = False
            self.segments = []
            self.on_end()

        return frame
