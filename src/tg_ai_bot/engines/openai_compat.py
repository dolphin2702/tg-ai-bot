import json
import logging
from typing import AsyncIterator

import httpx

from .base import Engine, EngineUnavailable, Message

log = logging.getLogger(__name__)

# HTTP statuses that indicate a transient problem — try next model.
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


class OpenAICompatEngine(Engine):
    """Works with any OpenAI-compatible /v1/chat/completions endpoint.

    Supports an ordered list of models with automatic failover: on 429/5xx
    or timeout, tries the next model, but only if nothing has been streamed
    to the caller yet.
    """

    def __init__(self, name: str, base_url: str, api_key: str, models: list[str]):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.models = list(models)

    @property
    def default_model(self) -> str:
        return self.models[0] if self.models else "—"

    def _ordered_models(self, override: list[str] | None) -> list[str]:
        """Merge user override with defaults, preserving order and uniqueness."""
        result: list[str] = []
        seen: set[str] = set()
        for m in (override or []):
            if m and m not in seen:
                result.append(m)
                seen.add(m)
        for m in self.models:
            if m and m not in seen:
                result.append(m)
                seen.add(m)
        return result

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _is_retryable(status: int) -> bool:
        return status in RETRYABLE_STATUS

    # ---------- plain chat ----------

    async def chat(
        self,
        messages: list[Message],
        *,
        thread_id: str | None = None,
        models: list[str] | None = None,
    ) -> AsyncIterator[str]:
        candidates = self._ordered_models(models)
        last_err: Exception | None = None

        for i, model in enumerate(candidates):
            yielded = False
            try:
                async for chunk in self._chat_one(messages, model):
                    yielded = True
                    yield chunk
                return
            except EngineUnavailable as e:
                last_err = e
                if yielded:
                    # Already started streaming — cannot switch now.
                    raise
                if i + 1 < len(candidates):
                    log.warning(
                        "engine %s: model %s unavailable (%s), trying %s",
                        self.name, model, e, candidates[i + 1],
                    )
                    continue
                raise
            except Exception as e:
                # Non-retryable — propagate immediately.
                raise

        if last_err:
            raise last_err

    async def _chat_one(self, messages: list[Message], model: str) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        timeout = httpx.Timeout(120.0, read=None)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=self._headers()) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        text = body[:300].decode("utf-8", "replace")
                        if self._is_retryable(resp.status_code):
                            raise EngineUnavailable(f"HTTP {resp.status_code}: {text}")
                        raise RuntimeError(f"HTTP {resp.status_code}: {text}")
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
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            raise EngineUnavailable(f"{type(e).__name__}: {e}")

    # ---------- agent mode ----------

    def supports_tools(self) -> bool:
        return True

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        models: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        candidates = self._ordered_models(models)
        last_err: Exception | None = None

        for i, model in enumerate(candidates):
            yielded = False
            try:
                async for event in self._chat_with_tools_one(messages, tools, model):
                    yielded = True
                    yield event
                return
            except EngineUnavailable as e:
                last_err = e
                if yielded:
                    raise
                if i + 1 < len(candidates):
                    log.warning(
                        "engine %s: model %s unavailable (%s), trying %s",
                        self.name, model, e, candidates[i + 1],
                    )
                    continue
                raise
            except Exception:
                raise

        if last_err:
            raise last_err

    async def _chat_with_tools_one(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
    ) -> AsyncIterator[dict]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": True,
        }
        timeout = httpx.Timeout(180.0, read=None)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=self._headers()) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        text = body[:300].decode("utf-8", "replace")
                        if self._is_retryable(resp.status_code):
                            raise EngineUnavailable(f"HTTP {resp.status_code}: {text}")
                        raise RuntimeError(f"HTTP {resp.status_code}: {text}")

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
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            raise EngineUnavailable(f"{type(e).__name__}: {e}")
