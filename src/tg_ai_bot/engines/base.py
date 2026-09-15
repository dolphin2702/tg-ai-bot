from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class Message:
    role: str      # "user" | "assistant" | "system"
    content: str


class Engine(ABC):
    """Common interface for all LLM backends."""

    name: str

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        thread_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Plain chat, yield text chunks. Raise on error."""
        ...

    def is_stateful(self) -> bool:
        """True if the backend keeps history server-side (AnythingLLM)."""
        return False

    async def new_thread(self, name: str | None = None) -> str | None:
        """Create a server-side thread. Only meaningful for stateful engines."""
        return None

    def supports_tools(self) -> bool:
        """Whether this engine can call OpenAI-style tools."""
        return False

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        """Agent mode. Only used if ``supports_tools()`` is True.

        Yields events:
            {"type": "text", "delta": "..."}
            {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
        """
        raise NotImplementedError
        yield  # noqa: pragma: no cover — make this an async generator
