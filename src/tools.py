import glob
import json
import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


load_dotenv()


def send_telegram(text: str):
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    token = os.getenv("TELEGRAM_TOKEN")
    url = "https://api.telegram.org/bot"
    url += token
    method = url + "/sendMessage"

    r = requests.post(method, data={"chat_id": channel_id, "text": text})

    if r.status_code != 200:
        print(r.text)
        raise Exception("post_text error")


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
                "name": "list_all_files",
                "description": """
                This function returns names of all available files.
                Files are stored in the context directory.
                They could be refered as context files.
                """,
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
                "name": "read_file",
                "description": """
                This function reads a file with specific name and returns it content.
                Use it if user asks to read (digest, absorb) a file.
                """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "File name without extention",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_to_vocabulary",
                "description": """Call this function to add a word or a phrase to the user's vocabulary.""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "word": {
                            "type": "string",
                            "description": "A word or a phrase to add to the vocabulary",
                        },
                    },
                    "required": ["word"],
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

    async def call(self, function_name: str, arguments: str):
        if function_name in self.function_names:
            if func := getattr(self, "tool_" + function_name):
                # FIXME: create_task?
                args_parsed = json.loads(arguments) if arguments else {}
                result = await func(**args_parsed)
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

    async def tool_get_local_date_time(self, *args, **kwargs):
        date = datetime.now().strftime("%Y-%m-%d")
        time = datetime.now().strftime("%H:%M:%S")
        res = f"The date is {date}, the local time is {time}"
        return res

    async def tool_list_all_files(self, *args, **kwargs):
        path = os.path.join(self.root_path, "context", "*.txt")
        files = []
        for name in glob.iglob(path):
            files.append(os.path.splitext(os.path.basename(name))[0])
        files.sort()
        return "\n".join(files)

    async def tool_read_file(self, name: str, **kwargs):
        path = os.path.join(self.root_path, "context", f"{name}.txt")
        if not os.path.isfile(path):
            return f"Error: file '{name}' not found"
        with open(path) as f:
            return f.read()

    async def tool_add_to_vocabulary(self, word):
        send_telegram(f"vocabulary: {word}")
        return "It is done."
