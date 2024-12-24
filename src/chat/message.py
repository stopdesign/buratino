from dataclasses import dataclass
from typing import Any, Literal, Union

ChatRole = Literal["system", "user", "assistant", "tool"]

ChatContent = Union[str]


@dataclass
class ChatMessage:
    role: ChatRole
    name: str | None = None
    content: ChatContent | list[ChatContent] | None = None
