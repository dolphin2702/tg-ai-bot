import json
from typing import AsyncIterator

import httpx

from .base import Engine, Message


class OpenAICompatEngine(Engine):
    """Works with any OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ---------- plain chat (no tools) ----------

    async def chat(
        self,
        messages: list[Message],
        *,
        thread_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model or self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        timeout = httpx.Timeout(120.0, read=None)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"HTTP {resp.status_code}: {body[:300].decode('utf-8', 'replace')}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    # ---------- agent mode (tools) ----------

    def supports_tools(self) -> bool:
        return True

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model or self.model,
            "messages": messages,
            "tools": tools,
            "stream": True,
        }
        timeout = httpx.Timeout(180.0, read=None)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"HTTP {resp.status_code}: {body[:300].decode('utf-8', 'replace')}"
                    )

                tool_calls: dict[int, dict] = {}
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}

                    content = delta.get("content")
                    if content:
                        yield {"type": "text", "delta": content}

                    tc_deltas = delta.get("tool_calls")
                    if tc_deltas:
                        for tcd in tc_deltas:
                            idx = tcd.get("index", 0)
                            slot = tool_calls.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tcd.get("id"):
                                slot["id"] = tcd["id"]
                            fn = tcd.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]

                for idx in sorted(tool_calls):
                    slot = tool_calls[idx]
                    try:
                        args = json.loads(slot["arguments"]) if slot["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {"_raw": slot["arguments"]}
                    yield {
                        "type": "tool_call",
                        "id": slot["id"],
                        "name": slot["name"],
                        "arguments": args,
                    }
