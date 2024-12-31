from dataclasses import dataclass
from typing import Any, Literal, Union

ChatRole = Literal["system", "user", "assistant", "tool"]

ChatContent = Union[str]


@dataclass
class ChatMessage:
    role: ChatRole
    name: str | None = None
    content: ChatContent | list[ChatContent] | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
