import asyncio
import json
import logging
import os
from datetime import datetime
from secrets import token_hex
from time import monotonic

from termcolor import colored, cprint

from chat import ChatContext, ChatMessage
from prompts import SP
from tools import ToolsHandler
from utils.lang import is_last_sentence_a_question
from workers.base import BaseWorker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Coordinator(BaseWorker):
    def __init__(self, event_bus):
        super().__init__(event_bus)
        self._request_id = None
        self.event_types = [
            "audio_chunk",
            "speech_started",
            "on_speech_final",
            "on_utterance_end",
            "llm_response",
            "llm_response_done",
            "on_speech_interim",
            "rtc_message",
            "on_vad_data",
            "on_vad_start",
            "on_vad_end",
            "llm_tool_calls",
            "tts_speech_started",
            "tts_speech_stopped",
        ]

        self.data_channel = None

        project_root = os.path.dirname(os.path.dirname(__file__))
        self.conversation_file = os.path.join(project_root, "db.jsonl")

        self.chat: ChatContext = ChatContext()
        self.tools = ToolsHandler(self.chat, root_path=project_root)

        date = datetime.now().strftime("%Y-%m-%d")
        self.system_prompt = SP.format(date=date)

        self.last_stt_time: float = monotonic() - 10
        self.last_vad_time: float = monotonic() - 10

        self.last_tts_time: float = monotonic() + 10
        self.tts_last_speech_start: float | None = None

        self.silence_duration: float = 10.0
        self.vad_active: bool = False

        self.unhandled_text = ""

        self.current_turn = 1

    def set_data_channel(self, channel):
        self.data_channel = channel

    async def start(self):
        await super().start()
        self.chat.append(role="system", content=self.system_prompt)
        self.tts_speech_active = False
        self.tts_last_speech_start = None

    async def handle_custom_message(self, message):
        match message["type"]:
            case "on_vad_start":
                self._handle_vad_start()
            case "on_vad_end":
                self._handle_vad_end()
            case "on_vad_data":
                self._handle_vad_data(message)
            case "on_speech_interim":
                self._handle_speech_interim(message)
            case "on_speech_final" | "on_utterance_end":
                await self._handle_speech_final(message)
            case "llm_response":
                self._handle_llm_response(message)
            case "llm_tool_calls":
                await self._handle_llm_tool_calls(message)
            case "llm_response_done":
                self._handle_llm_response_done(message)
            case "tts_speech_started":
                self.tts_speech_active = True
                self.tts_last_speech_start = monotonic()
            case "tts_speech_stopped":
                self.tts_speech_active = False
                self.tts_last_speech_start = None
            case "rtc_message":
                self._handle_rtc_message(message)

    def _handle_vad_start(self, message=None):
        # print()
        # cprint(" ⏵ ", "red", attrs=["reverse"])
        self.vad_active = True

    def _handle_vad_end(self, message=None):
        # cprint(" ⏹ ", "white", attrs=["reverse"])
        # print()
        self.vad_active = False

    def _abort_agent_speech(self):
        # TODO: переделать. Завести у чата свойство last_message / last_agent_message.
        # Завести у сообщений метод interrupt, который там сам решает.
        if self.tts_last_speech_start:
            played_time = monotonic() - self.tts_last_speech_start
            if played_time < 4.0:
                logger.warning(f"Interrupted at: {played_time:.3f}")
                self.chat.interrupt(turn=self.current_turn, time=played_time)

        # self.data_channel.send("abort")

        # TODO:
        # - downstream abort for the current nonce
        # - create a new nonce

        self.emit("tts_abort", {"reason": "vad", "turn": self.current_turn})
        self.emit("llm_abort", {"reason": "vad", "turn": self.current_turn})

    def should_take_turn(self) -> bool:
        #
        # TODO: analyze last tss interim for markers of incompleteness
        sp = self.last_vad_data["speech_prob"]

        silence_ratio_short = self.last_vad_data["silence_ratio_short"]
        silence_ratio_long = self.last_vad_data["silence_ratio_long"]
        mean_prob = self.last_vad_data["mean_prob"]

        question = is_last_sentence_a_question(self.unhandled_text)

        # pos_tags = get_pos_tags(last_sentence)
        # print("POS Tags:", pos_tags)
        # print("Is Complete:", is_phrase_complete(pos_tags))

        sd = self.silence_duration

        txt = f"sp: {sp:0.2f}  mean: {mean_prob:0.2f}  sd: {sd:0.2f}  q: {question}, silence short: {silence_ratio_short:0.2f}, silence long: {silence_ratio_long:0.2f}"
        # print(self.last_vad_data, semantic, " " * 10, end="\r")
        # speech_prob, pause_duration_soft/hard

        res = False
        reason = ""

        is_quiet_now = (sp < 0.1 and mean_prob < 0.05) or (sp < 0.01 and mean_prob < 0.01)

        if len(self.unhandled_text) < 50:
            # Есть вопрос и короткая пауза
            if question and is_quiet_now and sd > 0.5:
                reason += "question "
                res = True

            if is_quiet_now and silence_ratio_short > 0.9 and sd > 1:
                reason += "long silence "
                res = True

        else:
            if question:
                silence_th = 1
            elif self.unhandled_text.strip().endswith((".", "!")):
                silence_th = 2
            else:
                silence_th = 3

            last_part = self.unhandled_text[-300:].strip().lower()

            if "let me think" in last_part:
                silence_th = 3

            if "let me explain" in last_part:
                silence_th = 3

            if "let me finish" in last_part:
                silence_th = 3

            if is_quiet_now and silence_ratio_long > 0.9 and sd > silence_th:
                reason += "long text, long silence "
                res = True

        t = colored(txt, color="green" if res else "red")
        # print(t, reason)

        # pause_duration - не использовать напрямую, только для измерения уверенности

        return res

    def _handle_vad_data(self, message=None):
        """
        Здесь принимается решение о запуске хода компьютера.
        """
        if self.vad_active:
            self.last_vad_time = monotonic()
            self.silence_duration = 0.0
        else:
            self.silence_duration = monotonic() - self.last_vad_time

        # В такой тишине точно никакой текст копить не нужно
        if self.silence_duration > 6.0 and self.unhandled_text:
            logger.error(f"Reset old unhandled text: {self.unhandled_text}")
            self.unhandled_text = ""

        self.last_vad_data = message.get("payload")

        if not self.unhandled_text or not self.silence_duration:
            return

        try:
            if self.should_take_turn():
                self._process_user_speech(self.unhandled_text)
                self.unhandled_text = ""
        except Exception as e:
            logger.exception(e)

    def _process_user_speech(self, text):
        append = True
        start_llm = True
        clean_text = text.lower().strip(".").strip("!").strip()

        # Don't append technical commands
        if clean_text in ["stop", "pause"]:
            append = False
            start_llm = False

        # Timestamp
        dt = datetime.now().strftime("%H:%M:%S")
        text = f"[{dt}] {text}"

        # before the next line appended
        self._abort_agent_speech()

        self.current_turn += 1

        info = f"  {self.current_turn:03d}. {text} "
        cprint(info, "cyan" if append else "red", attrs=["reverse"])

        if append:
            self.chat.append(content=text, role="user")
            self.dump_history(self.chat.messages[-1])

        if start_llm:
            payload = {
                "chat_ctx": self.chat.context,
                "tools_ctx": self.tools.options,
                "turn": self.current_turn,
            }
            self.emit("llm_request", payload)

    def _handle_speech_interim(self, message):
        # text = message["payload"]["text"]

        # Если недавно была речь, то любой промежуточный результат считается,
        # как минимум, продолжением звуков речи
        if self.silence_duration < 3:  # TODO: check speech prob.
            self.last_vad_time = monotonic()

            # TODO: если у фразы высокая вероятность, то брать даже при > 3 s

            # TODO: отправить сигнал на фронтенд: mute for 500ms
            self._abort_agent_speech()

    async def _handle_speech_final(self, message):
        text = message["payload"]["text"]

        # TODO: отправить сигнал на фронтенд: mute for 500ms ???
        self._abort_agent_speech()

        if self.silence_duration > 3:
            # Это какой-то паразитный сигнал после долгой тишины, игнорировать.
            logger.error(f"Speech, no VAD, silence: {self.silence_duration:.2f}")
            self.unhandled_text = ""
        else:
            self.unhandled_text += f" {text}"

    def _handle_llm_response(self, message):
        """
        Handle responses from the LLM worker.
        """
        text = message["payload"]["text"]

        cprint(f"  {self.current_turn:03d}. {text} ", "magenta", attrs=["reverse"])

        self.chat.append(content=text, role="assistant")

        self.dump_history(self.chat.messages[-1])

        # Добавить текст в очередь на синтез и речь
        self.emit("tts_request", {"text": text, "turn": self.current_turn})
        self.last_tts_time = monotonic()

    def dump_history(self, msg: ChatMessage):
        """
        Сохранение сообщения для истории.
        """
        if msg and isinstance(msg, ChatMessage):
            try:
                with open(self.conversation_file, "a") as file:
                    file.write(msg.to_json() + "\n")
            except Exception as e:
                logger.error("ChatMessage to json error: %s", e)

    async def _handle_llm_tool_calls(self, message):
        """ """
        tool_calls = message["payload"]["tool_calls"]

        cprint(f"  {tool_calls} ", "yellow", attrs=["reverse"])

        self.chat.append(tool_calls=tool_calls, role="assistant")

        self.dump_history(self.chat.messages[-1])

        results = await self.tools.execute(tool_calls)

        # Append the result of each call
        for result in results:
            content = result["content"]
            cprint(f" 󰊕 {content} ", "blue")
            self.chat.append(content=content, tool_call_id=result["id"], role="tool")

            self.dump_history(self.chat.messages[-1])

        # Give a chance to wrap-up the llm task before creating another.
        await asyncio.sleep(0.01)

        # Call the LLM again to process the function call results
        payload = {"chat_ctx": self.chat.context, "turn": self.current_turn}
        self.emit("llm_request", payload)

    def _handle_llm_response_done(self, message):
        cprint(" LLM DONE ", attrs=["reverse"])

    def _handle_rtc_message(self, message):
        """
        Test client functions.
        """
        if message.get("payload") == "f3":
            self._abort_agent_speech()

        if message.get("payload") == "save_audio":
            self.emit("stt_save", {})

        if message.get("payload") == "time_test":
            # отправить tool message
            call_id = f"call_{token_hex(8).upper()}"

            task_text = (
                "CONDITION: when the function 'get_local_date_time' returns time grater than 12:45:00. "
                "ACTION: Ask the user how is he doing with his task and if he is late. "
                "If the condition is not satisfied, return [WAITING]. "
            )
            self.chat.append(content=task_text, role="system")

            # Bot wants to call a function
            tool_calls = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "get_local_date_time", "arguments": "{}"},
                }
            ]
            self.chat.append(tool_calls=tool_calls, role="assistant")

            # Here is the answer
            time = datetime.now().strftime("%H:%M:%S")
            content = f"Local time is {time}"
            self.chat.append(content=content, tool_call_id=call_id, role="tool")

            print()
            print(json.dumps(self.chat.context, indent=2, default=str))
            print()

            # Provide Bot with the answer
            payload = {"chat_ctx": self.chat.context, "turn": self.current_turn}
            self.emit("llm_request", payload)
