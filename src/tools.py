import json
import logging
import os

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
                "description": "Call this function when user asks to load context",
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

    @property
    def options(self) -> list[dict]:
        return self.tools

    async def call(self, function_name: str, arguments: dict):
        if function_name in ["get_current_weather", "load_context"]:
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

    async def tool_load_context(self, arguments):
        print()
        logger.error("HERE, load context")
        path = os.path.join(self.root_path, "context/day_1.txt")
        with open(path) as f:
            text = f.read()
            print(f"text len: {len(text)}")
            return text
