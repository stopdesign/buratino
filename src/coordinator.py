import logging
from time import monotonic

from termcolor import cprint

from chat import ChatContext
from workers.base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SP = (
    "1. You are a voice assistant. Your interface with users will be voice only. "
    "2. Your knowledge cutoff is October 2023. "
    "3. Your goal is to unobtrusively improve users conversational English. "
    "4. You are strict sometimes and not very supportive. "
    "5. No special formatting or headings. Don't use numbered lists. "
    "6. You use Speech-to-Text for user input. Do not assume perfect recognition. STT is "
    "imperfect and might misinterpret or autocorrect due to recognition errors or assumptions. "
    "7. Prioritize the context of the recognized sentence rather than detected "
    "spelling or grammar issues. "
    "8. If the phrase seems short and imcomplete, return [INCOMPLETE]. "
    "9. Ask When Uncertain. If unsure, ask clarifying questions like: 'Did you mean X?' "
    "IMPORTANT: always remember that you are a voice assistant with no visual interface. "
    "IMPORTANT: Avoid follow-up questions. Use laconic and concise language. "
)


class Coordinator(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self._request_id = None
        self.event_types = [
            "audio_chunk",
            "speech_started",
            "on_speech_final",
            "on_utterance_end",
            "llm_response",
            "llm_response_done",
            "abort_all",
            "on_speech_interim",
            "rtc_message",
            "on_vad_data",
            "on_vad_start",
            "on_vad_end",
        ]
        self.chat = ChatContext()
        self.system_prompt = SP

        self.last_stt_time: float = -1.0
        self.last_vad_time: float = -1.0
        self.silence_duration: float = 10.0
        self.vad_active: bool = False

        self.unhandled_text = ""

    async def start(self):
        await super().start()
        self.chat.append(role="system", text=self.system_prompt)

    async def handle_custom_message(self, message):
        match message["type"]:
            case "on_vad_start":
                await self._handle_vad_start()
            case "on_vad_end":
                await self._handle_vad_end()
            case "on_vad_data":
                await self._handle_vad_data()
            case "on_speech_interim":
                await self._handle_speech_interim(message)
            case "on_speech_final" | "on_utterance_end":
                await self._handle_speech_final(message)
            case "llm_response":
                await self._handle_llm_response(message)
            case "llm_response_done":
                await self._handle_llm_response_done(message)
            case "abort_all":
                await self._handle_abort(message)
            case "rtc_message":
                if message.get("payload") == "save_audio":
                    await self.emit("stt_save", {})

    async def _handle_vad_start(self, message=None):
        self.vad_active = True

    async def _handle_vad_end(self, message=None):
        self.vad_active = False

    async def _handle_vad_data(self, message=None):
        """
        Здесь принимается решение о запуске хода компьютера.

        Условия:
        - сейчас не говорят
        - есть накопленный текст
        - от текста зависит необходимая длина паузы
        """
        if self.vad_active:
            self.last_vad_time = monotonic()
            self.silence_duration = 0
        else:
            self.silence_duration = monotonic() - self.last_vad_time

        if self.unhandled_text and self.silence_duration > 1.0:
            cprint(f"  {self.unhandled_text} ", "cyan", attrs=["reverse"])

            self.chat.append(text=self.unhandled_text, role="user")
            self.unhandled_text = ""

            await self.emit("tts_abort", {})
            await self.emit("llm_request", self.chat.messages)

    async def _handle_speech_interim(self, message):
        text = message["payload"]["text"]
        confidence = float(message["payload"].get("confidence", 0))

        if text and confidence > 0.8:
            logger.error("TTS interruption by interim speech")
            await self.emit("tts_abort", {})

    async def _handle_speech_final(self, message):
        """
        Handle finalized speech events.
        """
        self.unhandled_text += " " + message["payload"]["text"]
        await self.emit("tts_abort", {})

    async def _handle_llm_response(self, message):
        """
        Handle responses from the LLM worker.
        """
        text = message.get("payload", {}).get("response", "--")

        cprint(f"  {text} ", "magenta", attrs=["reverse"])

        self.chat.append(text=text, role="assistant")

        # Добавить текст в очередь на синтез и речь
        await self.emit("tts_request", {"text": text})

    async def _handle_llm_response_done(self, message):
        cprint(" LLM DONE ", attrs=["reverse"])

    async def _handle_abort(self, message):
        """Handle abort events from workers or other components."""
        logger.error("HANDLE COORDINATOR ABORT")
