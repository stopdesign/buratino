import logging
from dataclasses import asdict, dataclass, field
from typing import Self

from .message import ChatContent, ChatMessage, ChatRole

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class ChatContext:
    """
    Менеджерит контекст чата. Подгружает и хранит нужное количество истории.

    Возможно, будут методы для получения короткого и длинного контекста.
    Системный промпт тоже здесь лежит.
    """

    messages: list[ChatMessage] = field(default_factory=list)

    def append(
        self,
        *,
        content: str = "",
        role: ChatRole = "system",
        tool_calls: list | None = None,
        tool_call_id: str | None = None,
    ) -> Self:
        content = ChatContent(content)
        message = ChatMessage(
            content=content,
            role=role,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        self.messages.append(message)
        return self

    @property
    def context(self):
        return [asdict(m) for m in self.messages if not m.interrupted_early]

    def interrupt(self, turn: int, time: float) -> None:
        """
        Marks the last agent message as interrupted, saves time played (ms);
        """
        for message in self.messages[-5:]:
            if message.turn == turn:
                message.interruption_time = int(time * 1000)  # convert to ms
                logger.error("INTERRUPTED:", message)

    # def copy(self) -> Self:
    #     copied_chat_ctx = ChatContext(messages=[m.copy() for m in self.messages])
    #     copied_chat_ctx._metadata = self._metadata
    #     return copied_chat_ctx
