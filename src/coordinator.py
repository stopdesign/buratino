import asyncio
import json
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
    "8. If the phrase seems short and imcomplete or irrelevant, return [INCOMPLETE]. "
    "9. Ask When Uncertain. If unsure, ask clarifying questions like: 'Did you mean X?' "
    "IMPORTANT: always remember that you are a voice assistant with no visual interface. "
    "IMPORTANT: Avoid follow-up questions. Use laconic and concise language. "
)


class Coordinator(BaseWorker):
    def __init__(self, event_bus, tts_track):
        super().__init__(event_bus)
        self._current_request_id = None
        self._awaiting_llm = False
        self._awaiting_tts = False
        self.event_types = [
            "audio_chunk",
            "speech_started",
            "on_speech_final",
            "on_utterance_end",
            "llm_response",
            "llm_response_done",
            "abort_all",
            "on_speech_interim",
        ]
        self.tts_track = tts_track
        self._ws = None
        # self._queue = asyncio.Queue()
        self.audio_queue = asyncio.Queue()
        self.chat = ChatContext()
        self.system_prompt = SP

    def set_ws(self, ws):
        self._ws = ws

    async def coordinate(self, forever=True):
        while True:
            await asyncio.sleep(0.01)
            audio_data = await self.audio_queue.get()
            if audio_data:
                await self._ws.send_bytes(audio_data)

    async def start(self):
        """Start the Coordinator and subscribe to relevant events."""
        await super().start()
        self.chat.append(role="system", text=self.system_prompt)

    async def handle_custom_message(self, message):
        """Process incoming messages based on their type."""
        # logger.info(f"HANDLE MSG: {message}")
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
            case "audio_chunk":
                await self.audio_queue.put(message["payload"])
            case "abort_all":
                await self._handle_abort(message)

    async def _handle_vad_speech_detected(self, message=None):
        logger.info("VAD update")

    async def _handle_vad_update(self, message=None):
        logger.info("VAD update")

    async def _handle_speech_started(self, message):
        pass

    async def _handle_speech_interim(self, message):
        text = message["payload"]["text"]
        confidence = float(message["payload"].get("confidence", 0))
        if text and confidence > 0.8 and self._awaiting_llm or self._awaiting_tts:
            logger.error("Interruption by interim speech")
            await self.abort_current_pipeline()

    async def _handle_speech_final(self, message):
        """Handle finalized speech events."""
        confidence = message["payload"].get("confidence")
        text = message["payload"]["text"]

        await self._ws.send_str(json.dumps({"request": text}))

        # Abort current pipeline if already awaiting responses
        if self._awaiting_llm or self._awaiting_tts:
            logger.error(f"waiting? llm: {self._awaiting_llm}, tts: {self._awaiting_tts}")
            await self.abort_current_pipeline()

        self._current_request_id = str(uuid.uuid4().hex)[:8]

        self._awaiting_llm = True

        cprint(f"  {text} ", "cyan", attrs=["reverse"])

        # commit speach
        self.chat.append(text=text, role="user")

        # TODO: form the payload from self.chat.messages

        await self.emit(
            "llm_request",
            self.chat.messages,
            request_id=self._current_request_id,
            confidence=confidence,
        )

    async def _handle_llm_response(self, message):
        """Handle responses from the LLM worker."""

        if message["request_id"] != self._current_request_id:
            return  # Ignore stale or unrelated responses

        if self._ws is not None:
            text = message.get("payload", {}).get("response", "--")
            cprint(f"  {text} ", "magenta", attrs=["reverse"])

            # commit assistant speach
            self.chat.append(text=text, role="assistant")

            self._awaiting_tts = True

            payload = {"text": text}
            await self.emit("tts_request", payload, request_id=self._current_request_id)
            await self._ws.send_str(json.dumps({"response": text}))

    async def _handle_llm_response_done(self, message):
        if message["request_id"] == self._current_request_id:
            self._awaiting_llm = False

    async def _handle_abort(self, message):
        """Handle abort events from workers or other components."""
        # Ensure we only act if the request ID matches the current pipeline
        if message["request_id"] == self._current_request_id:
            await self.abort_current_pipeline()

    async def abort_current_pipeline(self):
        """Abort any ongoing tasks in the LLM/TTS pipeline."""
        self._awaiting_llm = False
        self._awaiting_tts = False
        if self._current_request_id:
            if self._ws is not None:
                await self._ws.send_str(json.dumps({"abort": "yes"}))
            await self.emit("llm_abort", {}, request_id=self._current_request_id)
            await self.emit("tts_abort", {}, request_id=self._current_request_id)
