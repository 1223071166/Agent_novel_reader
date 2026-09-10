"""Data types shared by the chat service, storage layer, and API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatEvent:
    """A transport-neutral event emitted while processing one message."""
    event: str
    data: dict[str, Any]


@dataclass
class Message:
    id: str
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class Conversation:
    id: str
    messages: list[Message] = field(default_factory=list)
