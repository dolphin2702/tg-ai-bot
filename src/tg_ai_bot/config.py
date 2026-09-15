import os
from dataclasses import dataclass, field


def _env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


DEFAULT_SYSTEM_PROMPT = (
    "Ты — полезный ассистент. Отвечай чётко, по делу, на языке пользователя."
)


@dataclass
class EngineConfig:
    name: str
    type: str          # "openai_compat" | "anythingllm"
    params: dict


@dataclass
class Config:
    telegram_token: str
    redis_url: str | None
    default_engine: str
    engines: dict[str, EngineConfig]
    system_prompt: str
    allowed_users: set[int] = field(default_factory=set)
    allowed_chats: set[int] = field(default_factory=set)
    group_triggers: list[str] = field(default_factory=list)


def _load_engines() -> dict[str, EngineConfig]:
    engines: dict[str, EngineConfig] = {}

    # OpenAI-compatible engines, comma-separated names.
    names_raw = _env("OPENAI_ENGINES", default="") or ""
    for raw in names_raw.split(","):
        name = raw.strip().upper()
        if not name:
            continue
        lower = name.lower()
        base_url = _env(f"{name}_BASE_URL")
        if not base_url:
            # Not configured — skip silently. User may share .env across
            # machines where some engines are unavailable.
            continue
        model = _env(f"{name}_MODEL")
        if not model:
            raise RuntimeError(
                f"{name}_BASE_URL is set but {name}_MODEL is missing"
            )
        engines[lower] = EngineConfig(
            name=lower,
            type="openai_compat",
            params={
                "base_url": base_url,
                "api_key": _env(f"{name}_API_KEY", default="not-needed"),
                "model": model,
            },
        )

    # AnythingLLM (stateful).
    if _env("ANYTHINGLLM_URL"):
        engines["anythingllm"] = EngineConfig(
            name="anythingllm",
            type="anythingllm",
            params={
                "url": _env("ANYTHINGLLM_URL", required=True),
                "api_key": _env("ANYTHINGLLM_API_KEY", required=True),
                "workspace": _env("ANYTHINGLLM_WORKSPACE", default="default"),
            },
        )

    return engines


def _parse_ids(raw: str | None) -> set[int]:
    """Parse comma-separated numeric IDs. Negative numbers allowed (chat IDs)."""
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            pass
    return out


def load_config() -> Config:
    engines = _load_engines()
    if not engines:
        raise RuntimeError(
            "No engines configured. Set OPENAI_ENGINES and/or ANYTHINGLLM_URL."
        )
    default = _env("DEFAULT_ENGINE")
    if not default:
        default = next(iter(engines))
    if default not in engines:
        # Fall back gracefully: default engine is not configured on this host.
        fallback = next(iter(engines))
        # Warn via stderr; logging may not be set up yet.
        import sys
        print(
            f"WARNING: DEFAULT_ENGINE={default!r} not configured, "
            f"falling back to {fallback!r}",
            file=sys.stderr,
        )
        default = fallback
    triggers_raw = _env("GROUP_TRIGGERS", default="ИИ,AI,бот,bot") or ""
    group_triggers = [t.strip().lower() for t in triggers_raw.split(",") if t.strip()]
    return Config(
        telegram_token=_env("TELEGRAM_TOKEN", required=True),
        redis_url=_env("REDIS_URL"),
        default_engine=default,
        engines=engines,
        system_prompt=_env("SYSTEM_PROMPT", default=DEFAULT_SYSTEM_PROMPT)
                      or DEFAULT_SYSTEM_PROMPT,
        allowed_users=_parse_ids(_env("ALLOWED_USERS")),
        allowed_chats=_parse_ids(_env("ALLOWED_CHATS")),
        group_triggers=group_triggers,
    )