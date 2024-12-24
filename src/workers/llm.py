import asyncio
import logging
import os

import openai

from .base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class LLMWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.current_task = None
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)
        self.event_types = ["llm_request", "llm_abort"]

    async def handle_custom_message(self, message):
        match message["type"]:
            case "llm_request":
                request_id = message["request_id"]

                if self.current_task:
                    logger.error("Can't create a task, already running")
                    return

                logger.info("Create a task")
                try:
                    llm_coro = self._make_llm_call(message["payload"], request_id)
                    self.current_task = asyncio.create_task(llm_coro)
                except Exception as e:
                    logger.exception(e)
                finally:
                    self.current_task = None

            case "llm_abort":
                if self.current_task:
                    self.current_task.cancel()
                    self.current_task = None

    async def _make_llm_call_(self, payload, request_id):
        await self.emit("llm_started", {}, request_id=request_id)
        await asyncio.sleep(3)
        payload = {"response": "MOCK RESPONSE"}
        await self.emit("llm_response", payload, request_id=request_id)
        await self.emit("llm_response_done", {}, request_id=request_id)
        self.current_task = None

    async def _make_llm_call(self, payload, request_id):
        messages = []
        for message in payload:
            messages.append(
                {
                    "role": message.role,
                    "content": message.content,
                }
            )

        await self.emit("llm_started", {"request_id": request_id})

        buffer = ""
        sentences = []
        delimiter = (".", "!", "?", "\n", "\t", "-", ":", ";")

        try:
            completion = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.8,
                top_p=0.5,
                stream=True,
            )

            for chunk in completion:
                content = chunk.choices[0].delta.content

                if not content:
                    continue

                # Check if the chunk starts a new sentence
                if buffer.endswith(delimiter) and not content.startswith(delimiter):
                    buffer = buffer.lstrip()
                    payload = {"response": buffer, "first": not bool(sentences)}
                    sentences.append(buffer)
                    buffer = ""
                    await self.emit("llm_response", payload, request_id=request_id)

                buffer += content

            # Emit remaining buffer
            if buffer:
                buffer = buffer.lstrip()
                payload = {"response": buffer, "first": not bool(sentences)}
                sentences.append(buffer)
                await self.emit("llm_response", payload, request_id=request_id)

        except asyncio.CancelledError:
            logger.error("LLM request was aborted.")
        finally:
            self.current_task = None

            payload = {"sentences": sentences}
            await self.emit("llm_response_done", payload, request_id=request_id)

    async def handle_abort(self, request_id):
        print("ABORT LLM TASK", request_id)
        if self.current_task:
            self.current_task.cancel()
            self.current_task = None
