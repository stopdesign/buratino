import asyncio
import json
import os
import time
from datetime import datetime

from .base import BaseWorker


class EventTracer(BaseWorker):
    def __init__(self, event_bus, save_path="trace_events.json"):
        super().__init__(event_bus)
        self.save_path = save_path
        self.events = []
        self.event_types = ["*"]

    async def start(self):
        """Start tracing all events."""
        await super().start()

        # Create a template file
        metadata = {
            "source": "DevTools",
            "startTime": datetime.now().isoformat(),
            "networkThrottling": "No throttling",
            "dataOrigin": "TraceEvents",
        }
        content = {"metadata": metadata, "traceEvents": []}
        with open(self.save_path, "w") as f:
            f.write(json.dumps(content, indent=2, default=str))

    async def handle_custom_message(self, message):
        """Process incoming messages based on their type."""
        match message["type"]:
            case "speech_started":
                await self.trace_event("Speech", "S")
            case "on_speech_final" | "on_utterance_end":
                await self.trace_event("Speech", "E")
            # case "llm_request":
            #     pass
            # case "llm_response":
            #     await self._handle_llm_response(message)
            # case "llm_response_done":
            #     await self._handle_llm_response_done(message)
            case "abort_all":
                pass

    async def trace_event(self, name, phase="I", args=None):
        """Handle and record an incoming event."""
        timestamp = time.time()
        trace_event = {
            "ts": int(timestamp * 100),  # Convert to microseconds
            "ph": phase,
            "name": name,
            "cat": "event",
            "pid": 1,  # Process ID
            "tid": 1,  # Thread ID
            "args": args or {},
        }
        self.events.append(trace_event)
        # Periodically flush to disk
        if len(self.events) >= 1:
            await self.flush_to_disk()

    async def flush_to_disk(self):
        """Write buffered events to disk."""

        if not self.events:
            return

        # Prepare the JSON dumps for new events
        event_dumps = [json.dumps(event) for event in self.events]
        self.events = []

        with open(self.save_path, "r+") as f:
            # Move the pointer to the end of the file
            pos = f.seek(0, os.SEEK_END)

            # Scan backward for the closing of the traceEvents array
            while pos > 0:
                pos -= 1
                f.seek(pos, os.SEEK_SET)
                if f.read(1) == "]":
                    break

            # Find prev non-empty symbol
            has_events = False
            while pos > 0:
                f.seek(pos - 1, os.SEEK_SET)
                match f.read(1):
                    case " " | "\n":  # empty space
                        pos -= 1
                        continue
                    case "]" | "}":  # last element closing
                        has_events = True
                        break
                    case _:
                        break

            f.truncate(pos)
            f.seek(0, os.SEEK_END)

            if has_events:
                f.write(",")

            # Write the new events and restore the file structure
            f.write("\n    " + ",\n".join(event_dumps) + "\n  ]\n}")

    async def stop(self):
        """File footer"""
        await super().stop()
        await self.flush_to_disk()
