import struct


class OggProcessor:
    pageMagic = struct.unpack(">I", b"OggS")[0]
    headerMagic = struct.unpack(">Q", b"OpusHead")[0]
    commentMagic = struct.unpack(">Q", b"OpusTags")[0]

    def __init__(self, callback):
        self.callback = callback
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

        # Meta information from OpenAI API
        # {'magic': 'OpusHead', 'version': 1, 'channelCount': 1, 'sampleRate': 24000}
        print(magic, version, channelCount, preSkip, sampleRate, gain, channelMapping)

        self.meta = {
            "magic": magic,
            "version": version,
            "channelCount": channelCount,
            "sampleRate": sampleRate,
        }

    def onPage(self, page, headerSize, segmentSizes):
        if self.callback and self.meta:  # need the stream metadata
            i = headerSize
            for s in segmentSizes:
                self.callback(page[i : i + s], self.meta)
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
