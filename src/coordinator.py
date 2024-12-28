import logging
import uuid

from termcolor import cprint

from chat import ChatContext  # ChatContent, ChatMessage
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
    # "8. If the phrase seems short and imcomplete or irrelevant, return [INCOMPLETE]. "
    # "9. Ask When Uncertain. If unsure, ask clarifying questions like: 'Did you mean X?' "
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
        ]
        self.chat = ChatContext()
        self.system_prompt = SP

    async def start(self):
        await super().start()
        self.chat.append(role="system", text=self.system_prompt)

    async def handle_custom_message(self, message):
        match message["type"]:
            case "vad_speech_detected":
                await self._handle_vad_speech_detected()
            case "vad_speech_update":
                await self._handle_vad_update()
            case "speech_started":
                await self._handle_speech_started(message)
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
                if message.get("payload") == "speak":
                    print("SPEAK (do nothing)")

    async def _handle_vad_speech_detected(self, message=None):
        logger.info("VAD update")

    async def _handle_vad_update(self, message=None):
        logger.info("VAD update")

    async def _handle_speech_started(self, message):
        pass

    async def _handle_speech_interim(self, message):
        text = message["payload"]["text"]
        confidence = float(message["payload"].get("confidence", 0))

        # TODO:
        # - should interrupt?
        # - should mute the voice and wait? (pause TTS, don't stop LLM)

        if text and confidence > 0.8:
            logger.error("TTS interruption by interim speech")
            await self.emit("tts_abort", {})

    async def _handle_speech_final(self, message):
        """
        Handle finalized speech events.
        """
        confidence = message["payload"].get("confidence")
        text = message["payload"]["text"]

        # WARN:
        # - should_interrupt? YES, ALWAIS
        # - if yes, create LLM task (replace the current one, if any)
        # - update chat context witn a **precommited** message

        # TODO: создать объект, обрабатывающий данную порцию разговора
        self._request_id = str(uuid.uuid4().hex)[:8]

        cprint(f"  {text} ", "cyan", attrs=["reverse"])

        self.chat.append(text=text, role="user")

        await self.emit("tts_abort", {})
        await self.emit("llm_request", self.chat.messages)

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
        logger.info("LLM DONE ++++++++++++++++++++ (just a marker)")

    async def _handle_abort(self, message):
        """Handle abort events from workers or other components."""
        logger.error("HANDLE COORDINATOR ABORT")
