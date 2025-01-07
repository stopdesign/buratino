import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal, Union

ChatRole = Literal["system", "user", "assistant", "tool"]

ChatContent = Union[str]


@dataclass
class ChatMessage:
    ts: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    role: ChatRole | None = None
    name: str | None = None
    turn: int | None = None
    content: ChatContent | list[ChatContent] | None = None
    tool_call_id: str | None = None
    tool_calls: list | None = None
    interruption_time: int | None = None

    @property
    def interrupted_early(self) -> bool:
        return self.interruption_time and self.interruption_time < 3000

    def to_json(self) -> str:
        """Convert the dataclass instance to a JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False, default=str)
