import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ToolsHandler:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Get the current weather for a location.",
                # "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g., New York, NY.",
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["Celsius", "Fahrenheit"],
                            "default": "Celsius",
                        },
                    },
                    "required": ["location"],
                    # "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "load_context",
                "description": "Call this function when user asks to load context.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_local_date_time",
                "description": """Call this function when user asks date or time.
                Call it even it was called right before (because the time have changed).
                It is 24-hour notation, use it to read the time.
                """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    ]

    def __init__(self, chat_ctx, root_path):
        self.chat = chat_ctx
        self.root_path = root_path
        self.function_names = [t["function"]["name"] for t in self.tools]

    @property
    def options(self) -> list[dict]:
        return self.tools

    async def call(self, function_name: str, arguments: dict):
        if function_name in self.function_names:
            if func := getattr(self, "tool_" + function_name):
                # FIXME: create_task?
                result = await func(arguments)
                return result

    async def tool_get_current_weather(self, arguments):
        return "15 deg.C, no wind, no rain."

    def parse_args(self, tool_calls):
        for idx, data in tool_calls.items():
            args = json.loads(data["function"]["arguments"])
            tool_calls[idx]["function"]["arguments"] = args
        return tool_calls

    async def execute(self, tool_calls):
        for tool in tool_calls:
            function_name = tool["function"]["name"]
            arguments = tool["function"]["arguments"]
            result = await self.call(function_name, arguments)
            tool["content"] = result

        # TODO:
        # предполагается. что здесь можно модифицировать контекст,
        # если нужно, например, подгрузить архивные записи или задание
        #
        # С другой стороны, сейчас ЖПТ сам добавляет результат функции в контекст

        return tool_calls

    async def tool_get_local_date_time(self, arguments):
        date = datetime.now().strftime("%Y-%m-%d")
        time = datetime.now().strftime("%H:%M:%S")
        res = f"The date is {date}, the local time is {time}"
        return res

    async def tool_load_context(self, arguments):
        path = os.path.join(self.root_path, "context/day_3.txt")
        with open(path) as f:
            text = f.read()
            return text
