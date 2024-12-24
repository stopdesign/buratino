import asyncio
import json
import logging
import os

import coloredlogs
from aiohttp import web

from coordinator import Coordinator
from event_bus import EventBus
from workers.event_tracer import EventTracer
from workers.llm import LLMWorker
from workers.stt import STTWorker
from workers.tts import TTSWorker
from workers.vad import VADWorker

coloredlogs.install(
    "INFO",
    datefmt="%H:%M:%S.%f",
    fmt="%(asctime)s • %(levelname).1s • %(name)s • %(message)s",
)

logger = logging.getLogger("buratino_server")
logger.setLevel(logging.INFO)

logging.getLogger("event_bus").setLevel(logging.INFO)
logging.getLogger("websockets.client").setLevel(logging.INFO)
logging.getLogger("httpcore.http11").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=200)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


async def start_server(routes):
    app = web.Application(middlewares=[cors_middleware])
    app.add_routes(routes)

    runner = web.AppRunner(app, access_log=None, shutdown_timeout=5)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", 8080)
    await site.start()

    logger.info(f"Server started: {site.name}")


async def main():
    event_bus = EventBus()
    routes = web.RouteTableDef()

    stt = STTWorker(event_bus)

    llm = LLMWorker(event_bus)
    await llm.start()

    vad = VADWorker(event_bus)
    await vad.start()

    tts = TTSWorker(event_bus)
    await tts.start()

    event_tracer = EventTracer(event_bus)
    await event_tracer.start()

    coordinator = Coordinator(event_bus)

    @routes.get("/")
    async def index(request):
        path = os.path.join(os.path.dirname(__file__), "static/index.html")
        return web.FileResponse(path)

    routes.static("/", os.path.join(os.path.dirname(__file__), "static"))

    @routes.get("/ws")
    async def websocket_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(json.dumps({"status": "socket is ready"}))

        await stt.start()

        coordinator.set_ws(ws)

        async for msg in ws:
            if msg.type == web.WSMsgType.BINARY:
                # NOTE: here the audio data is fed to VAD and STT
                await vad.process(msg.data)
                await stt.on_voice_data(msg.data)

            elif msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)

                if data.get("command") == "start_recording":
                    await ws.send_str(json.dumps({"status": "start recording"}))

                elif data.get("command") == "stop_recording":
                    await ws.send_str(json.dumps({"status": "stop recording"}))
                    break

                elif data.get("command") == "do_something":
                    print("SOMETHING")
                    await ws.send_str(json.dumps({"status": "doing something"}))
                    await tts.ws_speak("Hello. Audio message 1. The new message.", ws)
                    await tts.ws_speak("Hello. Audio message 2. The new message.", ws)

            elif msg.type == web.WSMsgType.ERROR:
                logger.error(
                    f"WebSocket closed with exception: {
                        ws.exception()}"
                )

        await stt.finalize()
        await stt.stop()
        await event_bus.publish({"type": "llm_abort", "request_id": None})
        await event_bus.publish({"type": "abort_all", "request_id": None})
        # coordinator.set_ws(None)

        vad.reset()

        return ws

    await coordinator.start()

    try:
        await asyncio.gather(
            start_server(routes),
            coordinator.coordinate(),
            vad.run_forever(),
        )
    except asyncio.CancelledError:
        print("\nCancell Task")
        raise
    except KeyboardInterrupt:
        print()
    finally:
        await event_tracer.stop()
        await stt.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer interrupted. Exiting...")
