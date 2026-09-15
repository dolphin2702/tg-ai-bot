import json

try:
    import redis.asyncio as redis
except ImportError:
    redis = None


class State:
    """Per-user state. Uses Redis if URL is given, otherwise in-memory.
    Keys are namespaced under ``tgbot:``.
    """

    def __init__(self, url: str | None):
        if url:
            if redis is None:
                raise RuntimeError("redis package not installed but REDIS_URL is set")
            self._redis = redis.from_url(url, decode_responses=True)
            self._memory: dict[str, str] | None = None
        else:
            self._redis = None
            self._memory = {}

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    # ---- low-level ----
    async def _get(self, key: str) -> str | None:
        if self._redis:
            return await self._redis.get(key)
        return self._memory.get(key) if self._memory is not None else None

    async def _set(self, key: str, value: str) -> None:
        if self._redis:
            await self._redis.set(key, value)
        elif self._memory is not None:
            self._memory[key] = value

    async def _del(self, key: str) -> None:
        if self._redis:
            await self._redis.delete(key)
        elif self._memory is not None:
            self._memory.pop(key, None)

    # ---- engine selection ----
    async def get_engine(self, user_id: int, default: str) -> str:
        return await self._get(f"tgbot:user:{user_id}:engine") or default

    async def set_engine(self, user_id: int, engine: str) -> None:
        await self._set(f"tgbot:user:{user_id}:engine", engine)

    # ---- model override ----
    async def get_model(self, user_id: int, engine: str) -> str | None:
        return await self._get(f"tgbot:user:{user_id}:model:{engine}")

    async def set_model(self, user_id: int, engine: str, model: str) -> None:
        await self._set(f"tgbot:user:{user_id}:model:{engine}", model)

    async def clear_model(self, user_id: int, engine: str) -> None:
        await self._del(f"tgbot:user:{user_id}:model:{engine}")

    # ---- system prompt ----
    async def get_system(self, user_id: int) -> str | None:
        return await self._get(f"tgbot:user:{user_id}:system")

    async def set_system(self, user_id: int, prompt: str) -> None:
        await self._set(f"tgbot:user:{user_id}:system", prompt)

    async def clear_system(self, user_id: int) -> None:
        await self._del(f"tgbot:user:{user_id}:system")

    # ---- thread id ----
    async def get_thread(self, user_id: int, engine: str) -> str | None:
        return await self._get(f"tgbot:user:{user_id}:thread:{engine}")

    async def set_thread(self, user_id: int, engine: str, thread: str) -> None:
        await self._set(f"tgbot:user:{user_id}:thread:{engine}", thread)

    async def clear_thread(self, user_id: int, engine: str) -> None:
        await self._del(f"tgbot:user:{user_id}:thread:{engine}")

    # ---- local history ----
    async def get_history(self, user_id: int, engine: str) -> list[dict]:
        raw = await self._get(f"tgbot:user:{user_id}:history:{engine}")
        return json.loads(raw) if raw else []

    async def set_history(self, user_id: int, engine: str, messages: list[dict]) -> None:
        await self._set(
            f"tgbot:user:{user_id}:history:{engine}",
            json.dumps(messages),
        )

    async def clear_history(self, user_id: int, engine: str) -> None:
        await self._del(f"tgbot:user:{user_id}:history:{engine}")
