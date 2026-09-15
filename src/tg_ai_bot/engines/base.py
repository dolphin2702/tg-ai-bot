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
        """Yield text chunks. Raise on error."""
        ...

    def is_stateful(self) -> bool:
        """True if the backend keeps history server-side (AnythingLLM)."""
        return False

    async def new_thread(self) -> str | None:
        """Create a server-side thread. Only meaningful for stateful engines."""
        return None
