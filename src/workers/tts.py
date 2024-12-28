import asyncio
import logging
import os
from fractions import Fraction

from av import codec
from av.packet import Packet
from openai import AsyncOpenAI

from tracks.tts_track import TTSTrack
from utils.ogg_processor import OggProcessor

from .base import BaseWorker

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class TTSWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)

        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.event_types = ["tts_request", "tts_abort"]

        self.ttsTrack = TTSTrack(self.get_audio_packet)

        self.tts_queue = asyncio.Queue()
        self.packetq = asyncio.Queue()
        self.lock = asyncio.Lock()

        self.next_pts = 0
        self.silence_duration = 0.02
        self.time_base = 48000
        self.time_base_fraction = Fraction(1, self.time_base)

        self.gcodec = None
        self.gsample_rate = 0
        self.gchannels = 0

    async def start(self) -> None:
        await super().start()
        asyncio.create_task(self._process_tts_requests())

    async def handle_custom_message(self, message):
        match message["type"]:
            case "tts_request":
                await self._handle_tts_request(message)
            case "tts_abort":
                await self._handle_abort()

    async def _handle_abort(self):
        logger.warning("Aborting TTS tasks.")
        async with self.lock:
            while not self.tts_queue.empty():
                self.tts_queue.get_nowait()
                self.tts_queue.task_done()
            while not self.packetq.empty():
                self.packetq.get_nowait()
                self.packetq.task_done()
            self.next_pts = 0

    async def _handle_tts_request(self, message):
        text = message.get("payload", {}).get("text", "") + "\n"
        await self.tts_queue.put(text)

    async def _process_tts_requests(self):
        while self._running:
            # Process requests in the order they are queued
            text = await self.tts_queue.get()
            try:
                await self._requestTTS(text)
                await asyncio.sleep(0.5)  # rate limit
            except Exception as e:
                logger.error(f"Error processing TTS request: {e}")
            finally:
                self.tts_queue.task_done()

    async def _requestTTS(self, request):
        request_id = id(request)  # Unique ID for tracking request
        async with self.client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="alloy",
            input=request,
            response_format="opus",
        ) as response:
            oggProcessor = OggProcessor(self.on_segment)
            async for chunk in response.iter_bytes(chunk_size=4096):
                logger.info(f"Received chunk for request {request_id}")
                oggProcessor.addBuffer(chunk)

    def get_audio_packet(self):
        """
        Get an audio packet now or return silence.
        """
        try:
            duration, pts_count, chunk = self.packetq.get_nowait()
        except asyncio.QueueEmpty:
            duration = self.silence_duration
            pts_count = round(self.silence_duration * self.time_base)
            chunk = bytes.fromhex("f8fffe")

        pkt = Packet(chunk)
        pkt.pts = self.next_pts
        pkt.dts = self.next_pts
        pkt.time_base = self.time_base_fraction

        self.next_pts += pts_count

        return pkt, duration

    def on_segment(self, segment, meta):
        if self.gsample_rate != meta["sampleRate"] or self.gchannels != meta["channelCount"]:
            self._init_codec(meta["channelCount"], meta["sampleRate"])

        sample_count = sum(f.samples for f in self.gcodec.decode(Packet(segment)))

        duration = sample_count / self.gsample_rate
        pts_count = round(duration * self.time_base)

        self.packetq.put_nowait((duration, pts_count, segment))

    def _init_codec(self, channels, sample_rate):
        self.gcodec = codec.CodecContext.create("opus", "r")
        self.gcodec.sample_rate = sample_rate
        self.gcodec.channels = channels
        self.gsample_rate = sample_rate
        self.gchannels = channels
