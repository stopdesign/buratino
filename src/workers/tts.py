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
logger.setLevel(logging.WARNING)

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

        self.tts_speech_active = False

        self.speech_started = asyncio.Event()
        self.speech_stopped = asyncio.Event()

        self.next_pts = 0
        self.silence_duration = 0.02
        self.time_base = 48000
        self.time_base_fraction = Fraction(1, self.time_base)

        self.gcodec = None
        self.gsample_rate = 0
        self.gchannels = 0

        self.speech_stopped = asyncio.Event()

        self.current_turn = 0

    async def start(self) -> None:
        await super().start()
        asyncio.create_task(self._process_tts_requests(), name="process_tts")

        async def _queue_waiter_1(event):
            while self._running:
                await self.speech_started.wait()
                self.emit("tts_speech_started", {})
                self.speech_started.clear()

        async def _queue_waiter_2(event):
            while self._running:
                await self.speech_stopped.wait()
                self.emit("tts_speech_stopped", {"reason": "end"})
                self.speech_stopped.clear()

        asyncio.create_task(_queue_waiter_1(self.speech_started))
        asyncio.create_task(_queue_waiter_2(self.speech_stopped))

    async def handle_custom_message(self, message):
        match message["type"]:
            case "tts_request":
                await self._handle_tts_request(message)
            case "tts_abort":
                await self._handle_abort(message)

    async def _handle_abort(self, message):
        if self.tts_speech_active:
            self.tts_speech_active = False
            self.emit("tts_speech_stopped", {"reason": "abort"})

        last_aborted_turn = message["payload"]["turn"]
        logger.info(f"Aborting TTS tasks up to turn: {last_aborted_turn}")

        # FIXME: this                        vvvv
        self.current_turn = last_aborted_turn + 1

    async def _handle_tts_request(self, message):
        text = message["payload"]["text"] + "\n"
        turn = message["payload"]["turn"]
        await self.tts_queue.put((turn, text))

    async def _process_tts_requests(self):
        while self._running:
            # Process requests in the order they are queued
            turn, text = await self.tts_queue.get()
            if turn < self.current_turn or not self._running:
                self.tts_queue.task_done()
                continue
            try:
                await self._requestTTS(turn, text)
                if self._running:
                    await asyncio.sleep(1)  # rate limit
            except Exception as e:
                logger.error(f"Error processing TTS request: {e}")
            finally:
                self.tts_queue.task_done()

    async def _requestTTS(self, turn, request):
        request_id = id(request)  # Unique ID for tracking request
        async with self.client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="alloy",
            input=request,
            response_format="opus",
        ) as response:

            def on_segment_with_turn(segment, meta):
                if turn == self.current_turn:
                    self.on_segment(turn, segment, meta)

            oggProcessor = OggProcessor(on_segment_with_turn)

            logger.info(f"start chunks {request_id}")
            async for chunk in response.iter_bytes(chunk_size=4096):
                if turn < self.current_turn:
                    logger.error(f"Chunk for aborted turn {turn} [ct: {self.current_turn}]")
                    return
                oggProcessor.addBuffer(chunk)
                logger.info(f"Received chunk for request {request_id}")

            logger.info(f"end chunks {request_id}")
        logger.info(f"end request {request_id}")

    def get_audio_packet(self):
        """
        Get an audio packet now or return silence.
        """
        try:
            turn = -1
            while turn < self.current_turn:
                turn, duration, pts_count, chunk = self.packetq.get_nowait()
        except asyncio.QueueEmpty:
            duration = self.silence_duration
            pts_count = int(round(self.silence_duration * self.time_base))
            chunk = bytes.fromhex("f8fffe")

            if self.tts_speech_active:
                self.tts_speech_active = False
                self.speech_stopped.set()
        except Exception as e:
            logger.exception(e)

        pkt = Packet(chunk)
        pkt.pts = self.next_pts
        pkt.dts = self.next_pts
        pkt.time_base = self.time_base_fraction

        self.next_pts += pts_count

        return pkt, duration

    def on_segment(self, turn, segment, meta):
        if self.gsample_rate != meta["sampleRate"] or self.gchannels != meta["channelCount"]:
            self._init_codec(meta["channelCount"], meta["sampleRate"])

        sample_count = sum(f.samples for f in self.gcodec.decode(Packet(segment)))

        duration = sample_count / self.gsample_rate
        pts_count = round(duration * self.time_base)

        if not self.tts_speech_active:
            self.tts_speech_active = True
            self.speech_started.set()

        self.packetq.put_nowait((turn, duration, pts_count, segment))

    def _init_codec(self, channels, sample_rate):
        self.gcodec = codec.CodecContext.create("opus", "r")
        self.gcodec.sample_rate = sample_rate
        self.gcodec.channels = channels
        self.gsample_rate = sample_rate
        self.gchannels = channels
