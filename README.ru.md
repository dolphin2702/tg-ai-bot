# tg-ai-bot

[🇬🇧 English version](README.md)

Универсальный Telegram-бот для нескольких LLM-бэкендов. Один бот — много
движков: Ollama, LM Studio, OpenRouter, Mistral, OpenAI, AnythingLLM и любой
другой OpenAI-совместимый endpoint.

## Возможности

- **Несколько движков** — OpenAI-совместимые (Ollama, LM Studio, OpenRouter,
  Mistral, vLLM, ...) и AnythingLLM
- **Состояние на пользователя** — каждый выбирает свой движок, модель,
  системный промпт
- **Стриминг** — редактирование сообщения по мере генерации (там, где бэкенд
  поддерживает)
- **Системные промпты** — персональные, с настраиваемым дефолтом
- **Контроль доступа** — списки для личек (`ALLOWED_USERS`) и групп
  (`ALLOWED_CHATS`); удобно для семейного бота
- **Redis или in-memory** — Redis для продакшена, память для локальной разработки
- **Длинные ответы** — разбивка на сообщения по 4000 символов

## Команды

| Команда | Описание |
|---|---|
| `/start`, `/help` | Приветствие и список команд |
| `/id` | Показать твой `user_id` и `chat_id` |
| `/new` | Новый диалог (сброс истории / треда) |
| `/engine` | Список доступных движков |
| `/engine <name>` | Переключиться на другой движок |
| `/model` | Текущая модель |
| `/model <name>` | Задать свою модель для текущего движка |
| `/system` | Показать текущий системный промпт |
| `/system <текст>` | Задать свой системный промпт |
| `/system reset` | Сбросить на дефолтный |
| `/status` | Активный движок, модель, признак stateful |

## Движки

Поддерживаются два типа:

### `openai_compat`

Работает с любым endpoint, реализующим `/v1/chat/completions`:

- **Ollama** — `http://ollama:11434/v1`
- **LM Studio** — `http://<ip>:1234/v1`
- **OpenRouter** — `https://openrouter.ai/api/v1`
- **Mistral** — `https://api.mistral.ai/v1`
- **OpenAI** — `https://api.openai.com/v1`
- **vLLM / llama.cpp server / TGI** — свой URL

Можно добавить сколько угодно провайдеров. Каждый настраивается тремя переменными:
`<NAME>_BASE_URL`, `<NAME>_API_KEY`, `<NAME>_MODEL`.

### `anythingllm`

AnythingLLM хранит workspace и треды на своей стороне. Бот отправляет только
новое сообщение и id треда; системный промпт управляется внутри AnythingLLM,
поэтому `/system` для этого движка отключён.

## Установка

### Docker (рекомендуется)

```bash
docker pull ghcr.io/dolphin2702/tg-ai-bot:latest
```

### Из исходников

```bash
git clone git@github.com:dolphin2702/tg-ai-bot.git
cd tg-ai-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Конфигурация

Скопировать `.env.example` в `.env` и внести свои данные:

```bash
cp .env.example .env
```

| Переменная | По умолчанию | Описание |
|---|---|---|
| `TELEGRAM_TOKEN` | — | Токен бота от @BotFather (обязательно) |
| `ALLOWED_USERS` | `""` | Telegram user_id через запятую (личные чаты) |
| `ALLOWED_CHATS` | `""` | Telegram chat_id через запятую (группы) |
| `REDIS_URL` | `""` | URL Redis. Пусто = состояние в памяти |
| `SYSTEM_PROMPT` | встроенный | Дефолтный системный промпт |
| `DEFAULT_ENGINE` | первый из `OPENAI_ENGINES` | Движок по умолчанию |
| `OPENAI_ENGINES` | `""` | Имена OpenAI-совместимых движков через запятую |
| `<NAME>_BASE_URL` | — | Base URL движка `<NAME>` (обязательно) |
| `<NAME>_API_KEY` | `not-needed` | API-ключ движка `<NAME>` |
| `<NAME>_MODEL` | — | Дефолтная модель движка `<NAME>` (обязательно) |
| `ANYTHINGLLM_URL` | `""` | Base URL AnythingLLM (включает движок) |
| `ANYTHINGLLM_API_KEY` | — | API-ключ AnythingLLM |
| `ANYTHINGLLM_WORKSPACE` | `default` | Slug воркспейса |

### Пример `.env`

```env
TELEGRAM_TOKEN=123456:ABC...
ALLOWED_USERS=123456789,987654321
ALLOWED_CHATS=-1001234567890

REDIS_URL=redis://redis:6379/0

SYSTEM_PROMPT=Ты — полезный ассистент. Отвечай чётко, по делу на языке пользователя.

DEFAULT_ENGINE=lmstudio
OPENAI_ENGINES=lmstudio,openrouter,ollama

LMSTUDIO_BASE_URL=http://10.8.0.2:1234/v1
LMSTUDIO_API_KEY=sk-lm-xxxxxxxx
LMSTUDIO_MODEL=qwen2.5-7b-instruct

OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=sk-or-xxxxxxxx
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet

OLLAMA_BASE_URL=http://ollama:11434/v1
OLLAMA_API_KEY=ollama
OLLAMA_MODEL=llama3.1
```

## Запуск

```bash
# локально
set -a; source .env; set +a
tg-ai-bot

# либо без «загрязнения» окружения
env $(grep -v '^#' .env | grep -v '^$' | xargs) tg-ai-bot
```

### Docker Compose

```yaml
services:
  tg-ai-bot:
    image: ghcr.io/dolphin2702/tg-ai-bot:latest
    restart: unless-stopped
    env_file: .env
    depends_on: [redis]

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    volumes:
      - tg-ai-bot-redis:/data

volumes:
  tg-ai-bot-redis:
```

## Групповые чаты

Чтобы использовать бота в семейной группе:

1. Добавить бота в группу.
2. В @BotFather: `/mybots` → бот → **Bot Settings** → **Group Privacy** → **Turn off**
   (иначе бот видит только команды).
3. В группе отправь `/id` — скопируй отрицательный `chat_id`.
4. Впиши его в `ALLOWED_CHATS`.

У каждого участника всё равно своя история и свой движок (состояние на `user_id`).

## Разработка

```bash
git clone git@github.com:dolphin2702/tg-ai-bot.git
cd tg-ai-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# отредактируй .env
tg-ai-bot
```

## Лицензия

MIT