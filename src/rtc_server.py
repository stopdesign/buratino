import argparse
import asyncio
import json
import logging
import os
import uuid

import coloredlogs
from aiohttp import web
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaRecorder, MediaRelay
from silero_vad import load_silero_vad

from coordinator import Coordinator
from event_bus import EventBus
from tracks.tts_openai import TTSTrack
from workers.event_tracer import EventTracer
from workers.llm import LLMWorker
from workers.stt import STTWorker
from workers.tts import TTSWorker
from workers.vad2 import VADWorker

vad_model = load_silero_vad(onnx=True)

coloredlogs.install(
    "INFO",
    datefmt="%H:%M:%S.%f",
    fmt="%(asctime)s • %(levelname).1s • %(name)s • %(message)s",
)

logger = logging.getLogger("pc")
logger.setLevel(logging.INFO)

logging.getLogger("aioice.ice").setLevel(logging.WARNING)

pcs = set()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ROOT = os.path.dirname(__file__)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    ice_servers = ["stun:127.0.0.1:3478"]
    configuration = RTCConfiguration(iceServers=[RTCIceServer(urls=ice_servers)])
    pc = RTCPeerConnection(configuration)
    pcs.add(pc)

    pc_id = "PC_%s" % (uuid.uuid4().hex[:5]).upper()

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("Peer Connection created for %s", request.remote)

    relay = MediaRelay()  # копирует стрим в указанный трек

    # Main event bus
    event_bus = EventBus()

    stt = STTWorker(event_bus)

    llm = LLMWorker(event_bus)
    await llm.start()

    vad = VADWorker(event_bus)
    await vad.start()

    # tts = TTSWorker(event_bus)
    # await tts.start()

    event_tracer = EventTracer(event_bus)
    await event_tracer.start()

    tts_track = TTSTrack()

    coordinator = Coordinator(event_bus, tts_track)

    if args.save:
        recorder = MediaRecorder(args.save)
    else:
        recorder = MediaBlackhole()

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state: %s" % str(pc.connectionState).upper())
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("datachannel")
    async def on_datachannel(channel):
        @channel.on("message")
        async def on_message(message):
            if not isinstance(message, str):
                return
            if message.startswith("ping"):
                # Пинг и ответ на него
                channel.send("pong" + message[4:])
            else:
                # Проброс всех других сообщений в EventBus
                await event_bus.publish({"type": "rtc_message", "payload": message})

            # if isinstance(message, str) and message.startswith("speak"):
            #     await tts_track.say("Hello. How can I help you today?")
            #     channel.send("play")

    @pc.on("track")
    def on_track(track):
        log_info(f"Track received, kind={track.kind}")

        if track.kind == "audio":
            # NOTE: subscribe to audio data
            pc.addTrack(tts_track.getTrack())
            proxy_track = relay.subscribe(track)
            vad_track = vad.create_vad_track(proxy_track)
            recorder.addTrack(vad_track)

        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.kind)
            await recorder.stop()
            vad_model.reset_states()

    # handle offer
    await pc.setRemoteDescription(offer)
    await recorder.start()

    # send answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    content = json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    return web.Response(content_type="application/json", text=content)


async def index(request):
    content = open(os.path.join(ROOT, "static/rtc.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    content = open(os.path.join(ROOT, "static/client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    print("\nDONE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC audio demo")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--save", help="Write received media to a file.")
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    web.run_app(app, access_log=None, host=args.host, port=args.port)
