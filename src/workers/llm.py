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
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.event_types = ["llm_request", "llm_abort"]
        self.sentence_delimiter = (".", "!", "?", "\n", "\t", ";")

    async def handle_custom_message(self, message):
        match message.get("type"):
            case "llm_request":
                self.handle_abort()

                chat_ctx = message["payload"].get("chat_ctx")
                tools_ctx = message["payload"].get("tools_ctx")

                task_coro = self.make_llm_call(chat_ctx, tools_ctx)
                self.current_task = asyncio.create_task(task_coro)

            case "llm_abort":
                self.handle_abort()

    async def make_llm_call(self, chat_ctx, tools_ctx=None):
        params = dict(
            model=MODEL,
            messages=chat_ctx,
            temperature=0.8,
            top_p=0.6,
            stream=True,
        )
        if tools_ctx:
            params.update(
                tools=tools_ctx,
                tool_choice="auto",
                parallel_tool_calls=False,
            )

        try:
            result = await self.client.chat.completions.create(**params)

            async for part in self._group_chunks(result):
                if "text" in part:
                    self.emit("llm_response", part)

                if "tool_calls" in part:
                    self.emit("llm_tool_calls", part)

        except asyncio.CancelledError:
            logger.error("LLM request was aborted")

        finally:
            old_task = self.current_task
            self.current_task = None
            self.emit("llm_response_done", {"task": old_task})

    async def _group_chunks(self, completion):
        buffer = ""
        tool_calls = {}
        first = True

        async for chunk in completion:
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # Process content chunks
            if delta.content is not None:
                buffer += delta.content
                # Send the first chunk short(ly) to minimize latency
                min_len = 50 if first else 150
                if buffer.endswith(self.sentence_delimiter) and len(buffer) > min_len:
                    first = False
                    yield {"text": buffer.strip()}
                    buffer = ""

            # Process tool calls
            for tool_call in delta.tool_calls or []:
                # If there is id, then it must be a first function chunk
                if tool_call.id and tool_call.id not in tool_calls:
                    tool_calls[tool_call.index] = {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                # This must be an arguments chunk
                if not tool_call.id and tool_call.index in tool_calls:
                    if args := tool_call.function.arguments:
                        tool_calls[tool_call.index]["function"]["arguments"] += args

            # Process tool call with complete arguments
            if finish_reason == "tool_calls":
                # Yield all tool calls together
                yield {"tool_calls": list(tool_calls.values())}
                tool_calls = {}

        # Emit any remaining context buffer
        if buffer:
            yield {"text": buffer.strip()}

    def handle_abort(self):
        if self.current_task and not self.current_task.done():
            logger.error("Abort llm task")
            self.current_task.cancel()
            self.current_task = None
