# Copyright 2024 John Robinson
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file provides a streaming Opus client for OpenAI's TTS webservice.
# Provided a text string to the **say** function it will
# acquire and stream an opus string, will break the stream into
# individual opus segments which can be fed into an audio pipeline
# while the http request is still ongoing.

import logging
import os
import struct
from asyncio import sleep
from datetime import datetime
from fractions import Fraction
from time import time

from aiohttp import ClientSession
from aiortc.mediastreams import MediaStreamTrack
from av import codec
from av.packet import Packet

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class TTSTrack:
    def __init__(self):
        self.packetq = []
        self.next_pts = 0
        self.silence_duration = 0.02

        self.time_base = 48000
        self.time_base_fraction = Fraction(1, self.time_base)

        self.gcodec = None
        self.gsample_rate = 0
        self.gchannels = 0
        self._createTTSTrack()

        self.text = ""

    def clearAudio(self):
        self.packetq.clear()
        self.text = ""

    async def say(self, t):
        start = datetime.now()

        def on_segment(channels, sample_rate, segment):
            nonlocal start
            if start:
                delay = (datetime.now() - start).total_seconds()
                log.info(f"time to first segment: {delay:0.3f}")
                start = None

            if self.gsample_rate != sample_rate or self.gchannels != channels:
                self._init_codec(channels, sample_rate)

            sample_count = 0
            for frame in self.gcodec.decode(Packet(segment)):
                sample_count += frame.samples

            duration = sample_count / self.gsample_rate
            pts_count = round(duration * self.time_base)
            self.packetq.insert(0, (duration, pts_count, segment))

        await self._requestTTS(t, on_segment)

    async def open(self):
        self.text = ""

    async def write(self, text):
        self.text = self.text + text
        last_newline = max(self.text.rfind("\n"), self.text.rfind("."))
        if last_newline != -1:
            await self.say(self.text[: last_newline + 1])
            self.text = self.text[last_newline + 1 :]

    async def close(self):
        if self.text.strip():
            await self.say(self.text)
        self.txt = ""

    def getTrack(self):
        return self.ttsTrack

    ## -------------- internal impl --------------

    class _OggProcessor:
        pageMagic = struct.unpack(">I", b"OggS")[0]
        headerMagic = struct.unpack(">Q", b"OpusHead")[0]
        commentMagic = struct.unpack(">Q", b"OpusTags")[0]

        def __init__(self, cb):
            self.cb = cb
            self.buffer = b""
            self.meta = None

        def onMetaPage(self, page, headerSize):
            metaFormat = "<8sBBHIhB"
            metaSize = struct.calcsize(metaFormat)
            (magic, version, channelCount, preSkip, sampleRate, gain, channelMapping) = (
                struct.unpack_from(metaFormat, page, headerSize)
            )

            sampleRate *= 2  # Not sure why we need this...
            magic = magic.decode("utf-8")

            self.meta = {
                "magic": magic,
                "version": version,
                "channelCount": channelCount,
                "sampleRate": sampleRate,
            }

        def onPage(self, page, headerSize, segmentSizes):
            if self.cb and self.meta:  # need the stream metadata
                i = headerSize
                for s in segmentSizes:
                    self.cb(page[i : i + s], self.meta)
                    i = i + s

        # concat buffer and process all available pages
        # if we don't have enough data bail out and wait for more
        def addBuffer(self, b):
            self.buffer = self.buffer + b
            i = 0
            while len(self.buffer) >= i + 27:  # enough room for a header
                if self.pageMagic == struct.unpack_from(">I", self.buffer, i)[0]:
                    numSegments = struct.unpack_from("B", self.buffer, i + 26)[0]
                    headerSize = 27 + numSegments

                    if len(self.buffer) < i + headerSize:
                        return  # wait for more data

                    segmentSizes = struct.unpack_from("B" * numSegments, self.buffer, i + 27)
                    segmentTotal = sum(segmentSizes)
                    pageSize = headerSize + segmentTotal

                    if len(self.buffer) < i + pageSize:
                        return  # wait for more data

                    page = self.buffer[i : i + pageSize]
                    if self.headerMagic == struct.unpack_from(">Q", page, headerSize)[0]:
                        self.onMetaPage(page, headerSize)
                    elif self.commentMagic == struct.unpack_from(">Q", page, headerSize)[0]:
                        pass  # we don't do anything with comment pages
                    else:  # Assume audio page
                        self.onPage(page, headerSize, segmentSizes)
                    i = i + pageSize
                    self.buffer = self.buffer[i:]  # done with this page discarding
                    i = 0
                    continue
                i = i + 1

    def _createTTSTrack(self):
        def get_silence_packet(duration_seconds):
            chunk = bytes.fromhex("f8 ff fe")

            pkt = Packet(chunk)
            pkt.pts = self.next_pts
            pkt.dts = self.next_pts
            pkt.time_base = self.time_base_fraction

            pts_count = round(duration_seconds * self.time_base)
            self.next_pts += pts_count

            return pkt

        # if we we have audio queued deliver that; otherwise silence
        def get_audio_packet():
            if len(self.packetq) > 0:
                try:
                    duration, pts_count, chunk = self.packetq.pop()

                    pkt = Packet(chunk)
                    pkt.pts = self.next_pts
                    pkt.dts = self.next_pts
                    pkt.time_base = self.time_base_fraction

                    self.next_pts += pts_count

                    return pkt, duration
                except:
                    pass  # Ignore Empty exception

            return get_silence_packet(self.silence_duration), self.silence_duration

        class tts_track(MediaStreamTrack):
            kind = "audio"

            def __init__(self):
                super().__init__()
                self.stream_time = None
                log.info("create tts_track")

            async def close(self):
                super().stop()

            async def recv(self):
                try:  # exceptions that happen here are eaten... so log them
                    packet, duration = get_audio_packet()

                    if self.stream_time is None:
                        self.stream_time = time()

                    wait = self.stream_time - time()
                    await sleep(wait)

                    self.stream_time += duration
                    return packet
                except Exception as e:
                    log.error("Exception:", e)
                    raise

        self.ttsTrack = tts_track()

    # invoke OpenAI's TTS API with the provided text(t)
    # and process the returned Opus stream
    async def _requestTTS(self, t, callback):
        url = "https://api.openai.com/v1/audio/speech"

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "tts-1",
            "input": t,
            "voice": "alloy",  #'alloy',
            "response_format": "opus",
            "speed": 1.0,
        }

        async with ClientSession() as session:
            async with session.post(url=url, json=data, headers=headers, chunked=True) as response:

                def new_path(segment, meta):
                    callback(meta["channelCount"], meta["sampleRate"], segment)

                oggProcessor = TTSTrack._OggProcessor(new_path)
                if response.status != 200:
                    log.error("OpenAI TTS Call Failed Status:", response.status)

                async for data in response.content.iter_chunked(16384):
                    oggProcessor.addBuffer(data)

    def _init_codec(self, channels, sample_rate):
        self.gcodec = codec.CodecContext.create("opus", "r")

        self.gcodec.sample_rate = sample_rate
        self.gcodec.channels = channels

        self.gsample_rate = sample_rate
        self.gchannels = channels
