from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class Message:
    role: str      # "user" | "assistant" | "system"
    content: str


class EngineUnavailable(Exception):
    """Raised when the engine cannot serve a request right now.

    Signals that the caller may retry with a different model or backend.
    """
    pass


class Engine(ABC):
    """Common interface for all LLM backends."""

    name: str

    @property
    def default_model(self) -> str:
        """Display name of the primary model (first in the list)."""
        return "—"

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        thread_id: str | None = None,
        models: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """Plain chat. Yields text chunks. Raises on error.

        ``models`` is an ordered list of candidates. The engine tries them
        in order; on a retryable error (429/502/503/504/timeout) it moves to
        the next one, but only if no text has been yielded yet.
        """
        ...

    def is_stateful(self) -> bool:
        return False

    async def new_thread(self, name: str | None = None) -> str | None:
        return None

    def supports_tools(self) -> bool:
        return False

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        models: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        """Agent mode. Only used if ``supports_tools()`` is True.

        Yields events:
            {"type": "text", "delta": "..."}
            {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
        """
        raise NotImplementedError
        yield  # noqa: pragma: no cover
