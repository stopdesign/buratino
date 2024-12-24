from dataclasses import dataclass, field
from typing import Self

from .message import ChatMessage, ChatRole, ChatContent


@dataclass
class ChatContext:
    """
    Менеджерит контекст чата. Подгружает и хранит нужное количество истории.

    Возможно, будут методы для получения короткого и длинного контекста.
    Системный промпт тоже здесь лежит.
    """

    messages: list[ChatMessage] = field(default_factory=list)

    def append(self, *, text: str = "", role: ChatRole = "system") -> Self:
        self.messages.append(ChatMessage(content=ChatContent(text), role=role))
        return self

    # def copy(self) -> Self:
    #     copied_chat_ctx = ChatContext(messages=[m.copy() for m in self.messages])
    #     copied_chat_ctx._metadata = self._metadata
    #     return copied_chat_ctx
