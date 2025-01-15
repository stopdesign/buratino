import asyncio
import logging
import re
from collections import defaultdict

from termcolor import colored

from workers.base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FLASH = colored("", "magenta")  # 


class EventBus(BaseWorker):
    def __init__(self):
        super().__init__(self)
        self._skip_info = [
            "on_vad_data",
            "audio_chunk",
            "tts_abort",
            "llm_abort",
            "on_speech_interim",
            "on_speech_final",
        ]
        self.event_queue = asyncio.Queue()
        self.consumers = defaultdict(list)
        self._task: asyncio.Task | None = None

    def subscribe(self, callback, message_types: list | None = None):
        message_types = ["*"] if message_types is None else message_types
        for mt in message_types:
            self.consumers[mt].append(callback)

    def show_subs(self):
        for msg, subs in self.consumers.items():
            subs_str = ", ".join(re.search(r"<(\S+) ", str(s.__self__)).group(1) for s in subs)
            print(f"  {msg}: {subs_str}")

    def publish(self, message):
        try:
            self.event_queue.put_nowait((message.get("type", "*"), message))
        except Exception as e:
            logger.exception(e)

    async def _process_events(self) -> None:
        while self._running:
            event_type, event_data = await self.event_queue.get()
            if event_type not in self._skip_info:
                logger.info(f"{FLASH} {event_type}")
            for callback in self.consumers.get(event_type, []):
                asyncio.create_task(callback(event_data))
            self.event_queue.task_done()

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._process_events())

    async def stop(self) -> None:
        self._running = False
        self.event_queue.shutdown(immediate=True)

        if self._task:
            self._task.cancel()
        try:
            await asyncio.gather(self._task, self.event_queue.join(), return_exceptions=True)
        except Exception as e:
            logger.exception(e)

        await super().stop()
