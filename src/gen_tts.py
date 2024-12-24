# pip install openai pyaudio python-dotenv

import queue
import threading
from binascii import hexlify
from functools import reduce
from typing import Callable, Generator

import openai
import pyaudio
from dotenv import load_dotenv
from termcolor import cprint

# Load environment variables from .env file
load_dotenv()

# Constants
DELIMITERS = [f"{d} " for d in (".", "?", "!")]  # Determine where one phrase ends
MINIMUM_PHRASE_LENGTH = 200  # Minimum length of phrases to minimize audio choppiness
TTS_CHUNK_SIZE = 1024 * 30

# Default values
DEFAULT_RESPONSE_MODEL = "gpt-3.5-turbo"
DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_VOICE = "alloy"

# Prompt constants
AUDIO_FRIENDLY_INSTRUCTION = "Make sure your output is formatted in such a way that it can be read out loud (it will be turned into spoken words) from your response directly."
PROMPT_OPTIONS = {
    "getty": "explain the gettysburg address to a ten year old. then say the speech in a way they'd understand",
    "toast": "write a six sentence story about toast",
    "counter": "Count to 15, with a comma between each number, unless it's a multiple of 3 (including 3), then use only a period (ex. '4, 5, 6. 7,'), and no newlines. E.g., 1, 2, 3, ...",
    "punc": "say five senteces. each one ending with different punctuation. at least one question. each sentence should be at least 15 words long.",
}

PROMPT_TO_USE = f"{PROMPT_OPTIONS['getty']}. {AUDIO_FRIENDLY_INSTRUCTION}"

# Initialize OpenAI client.
# This uses OPENAI_API_KEY in your .env file implicitly.
OPENAI_CLIENT = openai.OpenAI()

# Global stop event
stop_event = threading.Event()


def stream_delimited_completion(
    messages: list[dict],
    client: openai.OpenAI = OPENAI_CLIENT,
    model: str = DEFAULT_RESPONSE_MODEL,
    content_transformers: list[Callable[[str], str]] = [],
    phrase_transformers: list[Callable[[str], str]] = [],
    delimiters: list[str] = DELIMITERS,
) -> Generator[str, None, None]:
    """Generates delimited phrases from OpenAI's chat completions."""

    def apply_transformers(s: str, transformers: list[Callable[[str], str]]) -> str:
        return reduce(lambda c, transformer: transformer(c), transformers, s)

    working_string = ""
    for chunk in client.chat.completions.create(messages=messages, model=model, stream=True):
        # if the global "all stop" happens, then send the sential value downstream
        # to help cease operations and exit this function right away
        if stop_event.is_set():
            yield None
            return

        content = chunk.choices[0].delta.content or ""
        if content:
            # Apply all transformers to the content before adding it to the working_string
            working_string += apply_transformers(content, content_transformers)
            while len(working_string) >= MINIMUM_PHRASE_LENGTH:
                delimiter_index = -1
                for delimiter in delimiters:
                    index = working_string.find(delimiter, MINIMUM_PHRASE_LENGTH)
                    if index != -1 and (delimiter_index == -1 or index < delimiter_index):
                        delimiter_index = index

                if delimiter_index == -1:
                    break

                phrase, working_string = (
                    working_string[: delimiter_index + len(delimiter)],
                    working_string[delimiter_index + len(delimiter) :],
                )
                yield apply_transformers(phrase, phrase_transformers)

    # Yield any remaining content that didn't end with the delimiter
    if working_string.strip():
        yield working_string.strip()

    yield None  # Sentinel value to signal "no more coming"


def phrase_generator(phrase_queue: queue.Queue):
    """Generates phrases and puts them in the phrase queue."""
    print(f"sending prompt:\n{PROMPT_TO_USE}\n- - - - - - - - - -")

    for phrase in stream_delimited_completion(
        messages=[{"role": "user", "content": PROMPT_TO_USE}],
        content_transformers=[
            lambda c: c.replace("\n", " ")
        ],  # If a line ends with a period, this helps it be recognized as a phrase.
        phrase_transformers=[
            lambda p: p.strip()
        ],  # Since each phrase is being used for audio, we don't need white-space
    ):
        # Sentinel (nothing more coming) signal received, so pass it downstream and exit
        if phrase is None:
            phrase_queue.put(None)
            return

        print(f"> {phrase}")
        phrase_queue.put(phrase)


def text_to_speech_processor(
    phrase_queue: queue.Queue,
    audio_queue: queue.Queue,
    client: openai.OpenAI = OPENAI_CLIENT,
    model: str = DEFAULT_TTS_MODEL,
    voice: str = DEFAULT_VOICE,
):
    """Processes phrases into speech and puts the audio in the audio queue."""
    while not stop_event.is_set():
        phrase = phrase_queue.get()
        # Got the signal that nothing more is coming, so pass that down and exit
        if phrase is None:
            audio_queue.put(None)
            return

        try:
            with client.audio.speech.with_streaming_response.create(
                model=model, voice=voice, response_format="pcm", input=phrase
            ) as response:
                cprint("\nTTS response", "yellow")
                for chunk in response.iter_bytes(chunk_size=TTS_CHUNK_SIZE):
                    cprint(f"chunk: {hexlify(chunk, " ")[:16]}", "magenta")
                    audio_queue.put(chunk)
                    if stop_event.is_set():
                        return
        except Exception as e:
            print(f"Error in text_to_speech_processor: {e}")
            audio_queue.put(None)
            return


def audio_player(audio_queue: queue.Queue):
    """Plays audio from the audio queue."""
    p = pyaudio.PyAudio()
    player_stream = p.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)

    try:
        while not stop_event.is_set():
            audio_data = audio_queue.get()
            # got the sentinel value that there's nothing more coming, so exit
            if audio_data is None:
                break
            player_stream.write(audio_data)
    except Exception as e:
        print(f"Error in audio_player: {e}")
    finally:
        player_stream.stop_stream()
        player_stream.close()
        p.terminate()


def wait_for_enter():
    """Waits for the Enter key press to stop the operation."""
    input("Press Enter to stop...\n\n")
    stop_event.set()
    print("STOP instruction received. Working to quit...")


def main():
    phrase_queue = queue.Queue()
    audio_queue = queue.Queue()

    phrase_generation_thread = threading.Thread(target=phrase_generator, args=(phrase_queue,))
    tts_thread = threading.Thread(target=text_to_speech_processor, args=(phrase_queue, audio_queue))
    audio_player_thread = threading.Thread(target=audio_player, args=(audio_queue,))

    phrase_generation_thread.start()
    tts_thread.start()
    audio_player_thread.start()

    # Create and start the "enter to stop" thread. Daemon means it will not block
    # exiting the script when all the other (non doemon) threads have completed.
    threading.Thread(target=wait_for_enter, daemon=True).start()

    phrase_generation_thread.join()
    print("## all phrases enqueued. phrase generation thread terminated.")
    tts_thread.join()
    print("## all tts complete and enqueued. tts thread terminated.")
    audio_player_thread.join()
    print("## audio output complete. audio player thread terminated.")


if __name__ == "__main__":
    main()
