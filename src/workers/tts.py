import asyncio
import io
import logging
import os
import queue
from binascii import hexlify

import openai
from termcolor import colored, cprint

from .base import BaseWorker

logger = logging.getLogger(__name__)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

CHUNK_SIZE = 1024 * 6


class TTSWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)
        self.event_types = ["tts_request", "tts_abort"]

    async def handle_custom_message(self, message):
        match message["type"]:
            case "tts_request":
                text = message.get("payload", {}).get("text")
                await self._speak(text)

    async def _speak(self, message: str) -> None:
        """
        Streams voice audio for a given message using OpenAI API.

        model: tts-1 or tts-1-hd
        format: mp3, opus, aac, flac, wav, and pcm
        voice: alloy, echo, fable, onyx, nova, and shimmer
        """
        logger.debug(message)
        with self.client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="alloy",
            input=message,
            response_format="pcm",
        ) as response:
            for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                await self.emit("audio_chunk", chunk)
                if not self._running:
                    break

    async def ws_speak(self, message: str, ws) -> None:
        """
        Test method to stream bytes directly into a websocket.
        """
        with self.client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="alloy",
            input=message,
            response_format="pcm",
        ) as response:
            for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                await ws.send_bytes(chunk)
                if not self._running:
                    break

    async def handle_abort(self, request_id):
        logger.info(f"Aborting request {request_id}")
        await self.stop()
