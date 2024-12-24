import asyncio
import re
import time


def extract_chunks(file_path):
    """
    Generator that splits a file into chunks based on a start and end pattern combination.
    Combines chunks by 7 before yielding, or yields remaining chunks if less than 7.
    """
    with open(file_path, "rb") as file:
        data = file.read()

    print("File len", len(data))

    prev = 0
    chunks = []

    # chunk by the same cuts as it was received
    while cut := data.find(b"\xa3\x43", prev) + 1:
        chunks.append(data[prev:cut])
        prev = cut

        # Combine and yield 7 small chunks at a time
        if len(chunks) == 7:
            yield b"".join(chunks)
            chunks = []

    # add the remaining chunks if any
    else:
        yield b"".join(chunks)


async def stream_chunks(file_path: str, ws_url: str, interval: float = 0.5):
    """
    Streams extracted chunks to a WebSocket server with dynamically adjusted delay.
    """
    async with websockets.connect(ws_url) as ws:
        print(f"Connected to WebSocket server at {websocket_url}")

        last_time = time.monotonic()

        for i, chunk in enumerate(extract_chunks(file_path), 1):
            # Send chunk to WebSocket server
            await ws.send(chunk)
            print(f"Sent chunk {i} with size {len(chunk)} bytes.")

            # Maintain consistent time intervals
            elapsed_time = time.monotonic() - last_time
            delay = max(0, interval - elapsed_time)
            await asyncio.sleep(delay)

            last_time = time.monotonic()

        print("Streaming complete. Waining...")
        await asyncio.sleep(5)
        print("DONE")


file_path = "./audio_log/20241214_220607.webm"
websocket_url = "ws://localhost:8080/ws"

asyncio.run(stream_chunks(file_path, websocket_url))
