from typing import AsyncIterator

import httpx

from .base import Engine, Message


class AnythingLLMEngine(Engine):
    """AnythingLLM keeps workspace + thread state on its side.
    We only send the last user message and a thread id."""

    def __init__(self, url: str, api_key: str, workspace: str):
        self.name = "anythingllm"
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.workspace = workspace

    def is_stateful(self) -> bool:
        return True

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def new_thread(self) -> str | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.url}/api/v1/workspace/{self.workspace}/thread/new",
                headers=self._headers(),
                json={"name": "tgbot"},
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("thread") or {}).get("id") or data.get("id")

    async def chat(
        self,
        messages: list[Message],
        *,
        thread_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        user_msg = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        payload: dict = {"message": user_msg, "mode": "chat"}
        if thread_id:
            payload["threadId"] = thread_id

        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                f"{self.url}/api/v1/workspace/{self.workspace}/chat",
                headers=self._headers(),
                json=payload,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            text = data.get("textResponse") or ""
            if not text:
                choices = data.get("choices") or []
                if choices:
                    text = (choices[0].get("message") or {}).get("content", "")
            # AnythingLLM doesn't stream via this API; yield once.
            yield text or "(empty response)"
