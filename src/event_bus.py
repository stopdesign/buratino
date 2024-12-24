import asyncio
import logging
import re

from termcolor import colored

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FLASH = colored("", "magenta")  # 


class EventBus:
    def __init__(self):
        self._subscribers = {}
        self._skip_info = ["llm_response", "audio_chunk", "on_vad_data"]

    def subscribe(self, callback, message_types: list | None = None):
        if message_types is None:
            message_types = ["*"]
        cb_str = re.search(r"<(\S+) ", str(callback.__self__)).group(1)
        mt_str = ", ".join(message_types)
        logger.debug(f"sub: <{cb_str}> to [{mt_str}]")
        for mt in message_types:
            if mt not in self._subscribers:
                self._subscribers[mt] = []
            self._subscribers[mt].append(callback)

    def show_subs(self):
        for msg, subs in self._subscribers.items():
            subs_str = ", ".join(re.search(r"<(\S+) ", str(s.__self__)).group(1) for s in subs)
            print(f"  {msg}: {subs_str}")

    async def publish(self, message):
        mt = message.get("type", "*")
        callbacks = self._subscribers.get(mt, []) + self._subscribers.get("*", [])
        if mt not in self._skip_info:
            logger.info(f"{FLASH} {mt}")  # ", {message.get("payload", "")}")
        tasks = [cb(message) for cb in callbacks]
        await asyncio.gather(*tasks)
