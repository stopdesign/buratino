import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiofiles import open as aio_open
from deepgram import AsyncLiveClient, DeepgramClientOptions, LiveOptions
from deepgram import LiveTranscriptionEvents as LTE
from dotenv import load_dotenv
from termcolor import colored

from event_bus import EventBus
from tracks.stt_track import STTTrack
from workers.base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


load_dotenv()


DT = "%H:%M:%S.%f"
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
AUDIO_LOG_PATH = os.path.join(os.path.dirname(__file__), "../audio_log/")


class STTWorker(BaseWorker):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self.is_finals = []
        self.last_start = datetime.now()
        self.rel_start = 0.0
        self.audio_data = bytearray(b"")

        # Configure live transcription options
        self.options = LiveOptions(
            model="nova-2",
            language="en-US",
            filler_words=True,
            profanity_filter=False,
            numerals=False,
            smart_format=True,
            punctuate=True,
            interim_results=True,
            utterance_end_ms="1000",
            vad_events=True,
            endpointing=300,
            ###
            encoding="linear16",
            channels=2,  # FIXME: make it mono
            sample_rate=48000,
        )

        self.addons = {"no_delay": "true"}

        client_options = DeepgramClientOptions(
            options={"keepalive": "true", "auto_flush_reply_delta": 1000},
            api_key=DEEPGRAM_API_KEY,
            verbose=logging.FATAL,  # logging.NOTSET,
        )

        self.deepgram = AsyncLiveClient(client_options)

        self.deepgram.on(LTE.Metadata, self.on_metadata)
        self.deepgram.on(LTE.UtteranceEnd, self.on_utterance_end)
        self.deepgram.on(LTE.Open, self.on_open)
        self.deepgram.on(LTE.SpeechStarted, self.on_speech_started)
        self.deepgram.on(LTE.Error, self.on_error)
        self.deepgram.on(LTE.Transcript, self.on_transcript)
        self.deepgram.on(LTE.Unhandled, self.on_unhandled)

    async def start(self):
        await super().start()
        await self.deepgram.start(self.options, self.addons)

    async def stop(self):
        logger.error("Stopping STT...")
        await self.deepgram.finalize()
        await asyncio.sleep(0.5)
        await self.deepgram.finish()
        await super().stop()

    async def finalize(self):
        logger.error("Finalize")
        file_name = await self.save_audio(self.audio_data)
        await self.emit("audio_log_ready", {"file_name": file_name})
        await self.deepgram.finalize()
        self.audio_data = bytearray(b"")
        self.is_finals = []

    async def save_audio(self, data):
        """
        Save the raw audio data to a file
        """
        file_name = datetime.now().strftime("%Y%m%d_%H%M%S")

        data_dir = os.path.abspath(AUDIO_LOG_PATH)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        file_path = os.path.join(data_dir, f"{file_name}.webm")

        async with aio_open(file_path, "wb") as f:
            await f.write(data)

        return file_name

    def create_track(self, track):
        return STTTrack(track, self.on_voice_data)

    async def on_voice_data(self, data):
        # self.audio_data += data
        # av.audio.frame.AudioFrame
        try:
            await self.deepgram.send(data)
        except Exception as e:
            logger.error(f"Error sending audio to Deepgram: {e}")

    async def handle_custom_message(self, message):
        # Handle specific messages sent to STTWorker
        if message["type"] == "stt_command":
            command = message["payload"].get("command", "")
            if command == "stop":
                await self.stop()

    async def on_open(self, *args, **kwargs):
        logger.info("STT Connection Opened")

    async def on_speech_started(self, caller, speech_started, **kwargs):
        self.last_start = datetime.now()
        # self.audio_data = b""
        # ts = float(speech_started.get("timestamp"))
        # self.rel_start = ts
        # await self._event_bus.publish({"type": "speech_started"})
        # logger.info(f"[{self.last_start:{DT}}]  Sound Detected")  # 󱦉

    async def on_transcript(self, caller, result, **kwargs):
        """Process transcription results."""
        if not result.channel.alternatives[0].transcript:
            return

        alt_chosen = result.channel.alternatives[0]
        transcript = alt_chosen.transcript
        prob = float(alt_chosen.confidence)
        rel_time = alt_chosen.words[0].start - self.rel_start
        dt = self.last_start + timedelta(seconds=rel_time)

        if result.is_final:
            self.is_finals.append(transcript)
            if result.speech_final:
                # combine all finals into a final sentence, reset finals
                utterance = " ".join(self.is_finals)
                self.is_finals = []
                txt = f"[{dt:{DT}}] 󰄴 {utterance}"
                txt = colored(txt, "green", attrs=["bold"])
                logger.info(txt)

                # EVENT
                payload = {"text": utterance, "confidence": prob}
                await self.emit("on_speech_final", payload)
            else:
                # Interim Result become final
                # For real time captioning and update what the Interim Results produced
                txt = f"[{dt:{DT}}] {transcript}"
                txt = colored(txt, "cyan")
                logger.ingo(txt)
        else:
            # Interim Results
            txt = f"[{dt:{DT}}] 󰇘 {transcript} // prob: {prob:.3f}"
            txt = colored(txt, "grey")
            logger.info(txt)
            payload = {"text": transcript, "confidence": prob}
            await self.emit("on_speech_interim", payload)

    async def on_utterance_end(self, caller, utterance_end, **kwargs):
        """Handle end of utterance."""
        stop = datetime.now()
        if self.is_finals:
            utterance = " ".join(self.is_finals)
            logger.info(f"[{stop:{DT}}]  {utterance}")
            self.is_finals = []

            # EVENT
            payload = {"text": utterance}
            await self.emit("on_utterance_end", payload)
        else:
            txt = f"[{stop:{DT}}]  [no new results]"
            txt = colored(txt, attrs=["bold"])
            logger.info(txt)

    async def on_metadata(self, caller, metadata, **kwargs):
        logger.info(f"Metadata, duration: {metadata.get('duration')}")

    async def handle_abort(self, request_id):
        logger.info(f"Aborting request {request_id}")
        await self.stop()

    async def on_error(self, caller, error, **kwargs):
        logger.info(f"Error occurred: {error}")

    async def on_unhandled(self, caller, unhandled, **kwargs):
        logger.error(f"Unhandled Websocket Error: {unhandled}")
