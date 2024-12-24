import abc
import asyncio
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BaseWorker(abc.ABC):
    def __init__(self, event_bus):
        self._event_bus = event_bus
        self._running = False
        self.event_types = []

    async def start(self):
        self._running = True
        self._event_bus.subscribe(self.handle_message, self.event_types + ["abort"])

    async def run_forever(self):
        while self._running:
            asyncio.sleep(1)

    async def stop(self):
        self._running = False
        logger.info(f"Stop worker {type(self).__name__}")

    async def emit(self, name, payload, /, **kwargs):
        pl = {"type": name, "payload": payload}
        pl.update(kwargs)
        await self._event_bus.publish(pl)

    async def handle_message(self, message):
        if message["type"] == "abort":
            await self.handle_abort(message["request_id"])
        else:
            await self.handle_custom_message(message)

    async def handle_abort(self, request_id):
        logger.error(f"Base Worker: Abort request {request_id}")

    async def handle_custom_message(self, message):
        pass
