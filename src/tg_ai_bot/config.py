import os
from dataclasses import dataclass, field


def _env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


DEFAULT_SYSTEM_PROMPT = (
    "Ты — дружелюбный ассистент в Telegram. Ты бот, работаешь внутри Telegram, "
    "отвечаешь пользователям в личных сообщениях и в групповых чатах. "
    "Не рассуждай о том, кто ты и где находишься — просто отвечай на вопрос. "
    "Отвечай на языке пользователя. Кратко, если вопрос простой.\n\n"

    "У тебя есть доступ к инструментам: поиск в интернете (search__*), "
    "долговременная память (memory__*) и кэш (cache__*). Используй их, когда уместно:\n"
    "- поиск — для актуальных данных (погода, новости, курсы, свежие события);\n"
    "- search__get_weather (city, days) — ТОЧНЫЙ прогноз погоды через Open-Meteo API.\n"
    "ИСПОЛЬЗУЙ ЭТОТ инструмент для ЛЮБЫХ вопросов про погоду, вместо web_search_xng.\n"
    "Он возвращает реальные цифры на 1-14 дней. Пример: search__get_weather(city="Санкт-Петербург", days=7)"
    "- память — чтобы сохранить важные факты о пользователе и найти прошлую информацию;\n"
    "- кэш — для временного хранения промежуточных данных.\n\n"
    
    "КРИТИЧЕСКИ ВАЖНО про даты:\n"
    "- Сегодня {date}, текущий год {year}. Это НАСТОЯЩЕЕ, не будущее.\n"
    "- Все даты в запросах пользователя («сегодня», «завтра», «через неделю», "
    "«в пятницу») считай относительно {date}.\n"
    "- «Завтра» = следующий день после {date}.\n"
    "- Если пользователь называет дату в {year} или ближайшие дни — "
    "отвечай как про настоящее, не отказывайся.\n"
    "- Твои внутренние знания о «текущем годе» УСТАРЕЛИ. Верь {date} из "
    "этого сообщения, а не своей памяти.\n\n"

    "КРИТИЧЕСКИ ВАЖНО при работе с поиском:\n"
    "- ВСЕГДА указывай текущий год ({year}) в поисковых запросах. "
    "Например: «погода в СПб 16 сентября {year}», а не «...2024».\n"
    "- Результаты поиска и загруженные страницы — ЕДИНСТВЕННЫЙ источник "
    "актуальных данных. Твои внутренние знания о погоде, новостях и курсах "
    "устарели и не отражают текущую реальность.\n"
    "- Если в результате поиска есть конкретные цифры (температура, курс, дата) — "
    "используй ИХ, не подменяй своими догадками и не «округляй».\n"
    "- Если в результате только заголовок и ссылка (без данных) — вызови "
    "fetch_article или fetch_web_content для нужного URL, чтобы получить содержимое.\n"
    "- Если цифр нигде нет — так и скажи: «в результатах поиска нет конкретных данных».\n"
    "- В ответе указывай источник (URL), откуда взял данные.\n\n"

    "Инструменты памяти:\n"
    "- Личные факты о пользователе → user_id = \"{user_id}_private\".\n"
    "- Справочные знания (термины, факты об организациях) → user_id = \"{user_id}\".\n"
    "- При противоречии: сначала search_memory, потом delete_memories, потом add_memories.\n"
    "- Ищи в памяти автоматически в начале диалога и при отсылках к прошлому.\n"
    "- Подтверждай запись только в конце ответа: «(Запомнил: …)»."
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
    history_limit: int = 50
    mcp_max_iter: int = 8
    mcp_servers: dict[str, str] = field(default_factory=dict)


def _load_engines() -> dict[str, EngineConfig]:
    engines: dict[str, EngineConfig] = {}

    names_raw = _env("OPENAI_ENGINES", default="") or ""
    for raw in names_raw.split(","):
        name = raw.strip().upper()
        if not name:
            continue
        lower = name.lower()
        base_url = _env(f"{name}_BASE_URL")
        if not base_url:
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


def _load_mcp_servers() -> dict[str, str]:
    servers: dict[str, str] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if key.startswith("MCP_") and key.endswith("_URL"):
            name = key[4:-4].lower()
            if name:
                servers[name] = value
    return servers


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
        fallback = next(iter(engines))
        import sys
        print(
            f"WARNING: DEFAULT_ENGINE={default!r} not configured, "
            f"falling back to {fallback!r}",
            file=sys.stderr,
        )
        default = fallback

    triggers_raw = _env("GROUP_TRIGGERS", default="ии,ai,бот,помощник") or ""
    group_triggers = [t.strip().lower() for t in triggers_raw.split(",") if t.strip()]

    history_limit = int(_env("HISTORY_LIMIT", default="50") or "50")
    mcp_max_iter = int(_env("MCP_MAX_ITER", default="8") or "8")
    mcp_servers = _load_mcp_servers()

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
        history_limit=history_limit,
        mcp_max_iter=mcp_max_iter,
        mcp_servers=mcp_servers,
    )
