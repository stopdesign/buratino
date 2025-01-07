import io
import logging
import os
from datetime import datetime

from deepgram import AsyncLiveClient, DeepgramClientOptions, LiveOptions, LiveResultResponse
from deepgram import LiveTranscriptionEvents as LTE
from dotenv import load_dotenv
from pydub import AudioSegment
from termcolor import colored

from tracks.stt_track import STTTrack
from utils.event_bus import EventBus
from workers.base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


load_dotenv()


DT = "%H:%M:%S.%f"
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
AUDIO_LOG_PATH = os.path.join(os.path.dirname(__file__), "../../audio_log/")


def stereo_to_mono(pcm_data: bytearray) -> bytes:
    """
    Convert stereo PCM audio (16-bit, 48kHz) to mono using pydub.
    """
    audio = AudioSegment.from_raw(
        io.BytesIO(pcm_data),
        sample_width=2,  # 16-bit audio = 2 bytes
        frame_rate=48000,
        channels=2,  # Stereo
    )
    mono_audio = audio.set_channels(1)
    return mono_audio.raw_data


class STTWorker(BaseWorker):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self.is_finals = []
        self.audio_data = bytearray(b"")

        self.event_types = ["stt_save"]

        # Configure live transcription options
        #
        # https://developers.deepgram.com/docs/understand-endpointing-interim-results
        #
        self.options = LiveOptions(
            model="nova-2",
            language="en-US",
            filler_words=False,
            profanity_filter=False,
            numerals=False,
            no_delay=True,  # не ждать номер после любой цифры
            smart_format=False,  # разметка текста
            #
            punctuate=True,
            #
            # The utterance_end feature is based on word timings,
            # and words can be detected in either final or interim results.
            # Interim results are created around once every second.
            # utterance_end_ms="3000",  # require interim_results=True
            #
            # Endpointing: bool or int (silence window, ms)
            # Time in milliseconds of silence to wait for before finalizing speech
            #
            # Uses VAD to detect silence and set the speech_final flag.
            #
            # Works well only in a silent environment.
            # A significant amount of background noise may prevent
            # the speech_final=true flag from being sent.
            #
            # By default, Deepgram identifies an endpoint after 10 milliseconds (ms) of silence.
            #
            endpointing=100,  # for SPEECH_FINAL (VAD PAUSE)
            #
            # Interim Results feature
            interim_results=True,  # for IS_FINAL=True/False - identifies if the text is final
            ###
            vad_events=False,  # события SpeechStarted
            ###
            encoding="linear16",
            channels=2,
            sample_rate=48000,
        )

        # TODO: test this:
        # auto_flush_speak_delta
        # endpointing
        # punctuate

        client_options = DeepgramClientOptions(
            options={"keepalive": "true", "auto_flush_speak_delta": 500},
            api_key=DEEPGRAM_API_KEY,
            verbose=logging.FATAL,  # мало логов
            # verbose=logging.NOTSET,  # много логов
            # verbose=logging.DEBUG,  # много логов
        )

        self.deepgram = AsyncLiveClient(client_options)

        self.deepgram.on(LTE.Open, self.on_open)
        self.deepgram.on(LTE.Close, self.on_close)
        self.deepgram.on(LTE.Transcript, self.on_transcript)
        self.deepgram.on(LTE.Metadata, self.on_metadata)
        self.deepgram.on(LTE.UtteranceEnd, self.on_utterance_end)
        self.deepgram.on(LTE.SpeechStarted, self.on_speech_started)
        self.deepgram.on(LTE.Finalize, self.on_finalize)
        self.deepgram.on(LTE.Error, self.on_error)
        self.deepgram.on(LTE.Unhandled, self.on_unhandled)
        self.deepgram.on(LTE.Warning, self.on_error)

    async def start(self):
        await super().start()
        res = await self.deepgram.start(self.options)
        connected = await self.deepgram.is_connected()
        print(colored(f"start res: {res}, con: {connected}", "red"))
        if not connected:
            raise Exception("DG not connected")

    async def stop(self):
        logger.warning("Stop STT...")
        await self.deepgram.finish()
        logger.info("Deepgram finished")
        await super().stop()

    async def handle_custom_message(self, message):
        match message["type"]:
            case "stt_save":
                self.save()

    def save(self):
        if not self.audio_data:
            return
        logger.warning("Saving audio...")
        file_name = self.save_audio(self.audio_data)
        self.emit("audio_log_ready", {"file_name": file_name})
        self.audio_data = bytearray(b"")
        self.is_finals = []

    def save_audio(self, pcm_data):
        """
        Save the raw audio data to a compressed file.
        """
        file_name = datetime.now().strftime("%Y%m%d_%H%M%S")

        data_dir = os.path.abspath(AUDIO_LOG_PATH)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        file_path = os.path.join(data_dir, f"{file_name}.mp3")

        audio = AudioSegment.from_raw(
            io.BytesIO(pcm_data),
            sample_width=2,
            frame_rate=48000,
            channels=2,
        )
        audio.export(file_path, format="mp3", bitrate="160k")

        logger.info(f"Saved audio duration: {audio.duration_seconds}")

        return file_name

    def create_track(self, track):
        return STTTrack(track, self.on_voice_data)

    async def on_voice_data(self, data):
        # takes 0.1-0.2 ms
        # data = stereo_to_mono(data)
        self.audio_data += data
        await self.deepgram.send(data)

    async def on_open(self, *args, **kwargs):
        logger.info("STT Connection Opened")

    async def on_close(self, *args, **kwargs):
        logger.warning("STT Connection Closed")

    async def on_speech_started(self, caller, speech_started, **kwargs):
        txt = f" speech started (at: {speech_started.timestamp:0.2f})"
        logger.info(colored(txt, "blue", attrs=["reverse"]))

    async def on_transcript(self, caller, result: LiveResultResponse, **kwargs):
        """Process transcription results."""

        try:
            alt_chosen = result.channel.alternatives[0]
            transcript = alt_chosen.transcript
            prob = float(alt_chosen.confidence)
        except Exception as e:
            transcript = "--"
            prob = -0.1
            logger.exception(e)

        if prob == 0:
            return

        try:
            label = ""
            if result.is_final:
                d = result.duration
                label = colored(f" FINAL (dur: {d:0.2f}) ", "green", attrs=["reverse"])
            else:
                label = colored(" Interim Result ", "yellow", attrs=["reverse"])
            if result.speech_final:
                label += "  " + colored(" VAD PAUSE ", "magenta", attrs=["reverse"])

            label += f"  {prob:0.2f}  {transcript} "
            logger.info(label)

        except Exception as e:
            logger.exception(e)

        payload = {"text": transcript, "confidence": prob}

        if result.is_final:
            self.emit("on_speech_final", payload)
        else:
            self.emit("on_speech_interim", payload)

    async def on_utterance_end(self, caller, utterance_end, **kwargs):
        """Handle end of utterance."""

        logger.info(colored("  ON_UTTERANCE_END ", "red", attrs=["reverse"]))

        stop = datetime.now()
        if self.is_finals:
            utterance = " ".join(self.is_finals)
            logger.info(f"[{stop:{DT}}]  {utterance}")
            self.is_finals = []

            # EVENT
            payload = {"text": utterance}
            self.emit("on_utterance_end", payload)
        else:
            txt = f"[{stop:{DT}}]  [no new results]"
            txt = colored(txt, attrs=["bold"])
            logger.info(txt)

    async def on_metadata(self, caller, metadata, **kwargs):
        # logger.error(colored("METADATA", "red"))
        logger.error(f"METADATA, duration: {metadata.get('duration')}")

    async def on_finalize(self, caller, *args, **kwargs):
        logger.error(" ON FINALIZE ")

    async def on_error(self, caller, error, **kwargs):
        logger.info(f"Error occurred: {error}")

    async def on_unhandled(self, caller, unhandled, **kwargs):
        logger.error(f"Unhandled Websocket Error: {unhandled}")
