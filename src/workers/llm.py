import asyncio
import logging
import os

from openai import AsyncOpenAI

from workers.base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class LLMWorker(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self.current_task = None
        # client = OpenAI(timeout=httpx.Timeout(300.0, read=20.0, write=20.0, connect=10.0))
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.event_types = ["llm_request", "llm_abort"]

    async def handle_custom_message(self, message):
        match message["type"]:
            case "llm_request":
                if self.current_task:
                    logger.error("Already running LLM, ABORT")
                    await self.handle_abort()
                    return

                logger.info("Create a task")
                self.current_task = asyncio.create_task(self.make_llm_call(message["payload"]))

            case "llm_abort":
                if self.current_task:
                    self.current_task.cancel()
                    self.current_task = None

    async def make_llm_call(self, payload):
        messages = []
        for message in payload:
            messages.append({"role": message.role, "content": message.content})

        await self.emit("llm_started", {})

        buffer = ""
        sentences = []
        delimiter = (".", "!", "?", "\n", "\t", "-", ":", ";")

        try:
            completion = await self.client.chat.completions.create(
                model=MODEL, messages=messages, temperature=0.8, top_p=0.5, stream=True
            )

            async for chunk in completion:
                content = chunk.choices[0].delta.content

                if not content:
                    continue

                # Check if the chunk starts a new sentence
                if buffer.endswith(delimiter) and not content.startswith(delimiter):
                    buffer = buffer.lstrip()
                    payload = {"response": buffer, "first": not bool(sentences)}
                    sentences.append(buffer)
                    buffer = ""
                    await self.emit("llm_response", payload)

                buffer += content

            # Emit remaining buffer
            if buffer:
                buffer = buffer.lstrip()
                payload = {"response": buffer, "first": not bool(sentences)}
                sentences.append(buffer)
                await self.emit("llm_response", payload)

        except asyncio.CancelledError:
            logger.error("LLM request was aborted.")

        finally:
            self.current_task = None

            payload = {"sentences": sentences}
            await self.emit("llm_response_done", payload)

    async def handle_abort(self, request_id=None):
        print("ABORT LLM TASK", request_id)
        if self.current_task:
            self.current_task.cancel()
            self.current_task = None
