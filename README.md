# Description

Universal Telegram bot for multiple LLM backends. One bot, many engines —
switch between Ollama, LM Studio, OpenRouter, Mistral, OpenAI, AnythingLLM
and any other OpenAI-compatible endpoint.

## Features

- **Multiple engines** — OpenAI-compatible (Ollama, LM Studio, OpenRouter,
  Mistral, vLLM, ...) and AnythingLLM
- **Per-user state** — each user picks their own engine, model, system prompt
- **Streaming** — token-by-token edits in Telegram where the backend supports it
- **System prompts** — per-user, with a configurable default
- **Access control** — allow lists for private chats (`ALLOWED_USERS`) and
  groups (`ALLOWED_CHATS`); works well for a family bot
- **Redis or in-memory** — Redis for production, in-memory for local dev
- **Graceful multi-message** — long answers split into 4000-char chunks

## Commands

| Command | Description |
|---|---|
| `/start`, `/help` | Greeting and command list |
| `/id` | Show your `user_id` and `chat_id` |
| `/new` | Start a new dialog (clear history / thread) |
| `/engine` | List available engines |
| `/engine <name>` | Switch to another engine |
| `/model` | Show current model |
| `/model <name>` | Override model for current engine |
| `/system` | Show current system prompt |
| `/system <text>` | Set a personal system prompt |
| `/system reset` | Reset to the default prompt |
| `/status` | Show active engine, model, stateful flag |

## Engines

Two engine types are supported:

### `openai_compat`

Works with any endpoint implementing `/v1/chat/completions`:

- **Ollama** — `http://ollama:11434/v1`
- **LM Studio** — `http://<mac-ip>:1234/v1`
- **OpenRouter** — `https://openrouter.ai/api/v1`
- **Mistral** — `https://api.mistral.ai/v1`
- **OpenAI** — `https://api.openai.com/v1`
- **vLLM / llama.cpp server / TGI** — your own URL

Add as many as you like. Each is configured with three env vars:
`<NAME>_BASE_URL`, `<NAME>_API_KEY`, `<NAME>_MODEL`.

### `anythingllm`

AnythingLLM keeps workspace + thread state on its side. The bot sends only
the new message and a thread id; system prompts are managed inside AnythingLLM,
so `/system` is disabled for this engine.

## Installation

### Docker (recommended)

```bash
docker pull ghcr.io/dolphin2702/tg-ai-bot:latest
```

### From source

```bash
git clone git@github.com:dolphin2702/tg-ai-bot.git
cd tg-ai-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | — | Bot token from @BotFather (required) |
| `ALLOWED_USERS` | `""` | Comma-separated Telegram user IDs (private chats) |
| `ALLOWED_CHATS` | `""` | Comma-separated Telegram chat IDs (groups) |
| `REDIS_URL` | `""` | Redis URL. Empty = in-memory state |
| `SYSTEM_PROMPT` | built-in | Default system prompt |
| `DEFAULT_ENGINE` | first in `OPENAI_ENGINES` | Engine used by default |
| `OPENAI_ENGINES` | `""` | Comma-separated names of OpenAI-compatible engines |
| `<NAME>_BASE_URL` | — | Base URL for engine `<NAME>` (required if listed) |
| `<NAME>_API_KEY` | `not-needed` | API key for engine `<NAME>` |
| `<NAME>_MODEL` | — | Default model for engine `<NAME>` (required if listed) |
| `ANYTHINGLLM_URL` | `""` | AnythingLLM base URL (enables the engine) |
| `ANYTHINGLLM_API_KEY` | — | AnythingLLM API key |
| `ANYTHINGLLM_WORKSPACE` | `default` | Workspace slug |

See `.env.example` for a ready-to-edit template.

### Example `.env`

```env
TELEGRAM_TOKEN=123456:ABC...
ALLOWED_USERS=123456789,987654321
ALLOWED_CHATS=-1001234567890

REDIS_URL=redis://redis:6379/0

SYSTEM_PROMPT=Ты — полезный ассистент. Отвечай чётко, по делу.

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

## Run

```bash
# local
set -a; source .env; set +a
tg-ai-bot

# or, without polluting your shell env
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

## Group chats

To use the bot in a family group:

1. Add the bot to the group.
2. In @BotFather: `/mybots` → your bot → **Bot Settings** → **Group Privacy** → **Turn off**
   (otherwise the bot sees only commands).
3. In the group, send `/id` — copy the negative `chat_id`.
4. Put it in `ALLOWED_CHATS`.

Each member still has their own history and engine choice (state is per `user_id`).

### Group triggers

In groups, the bot responds **only when addressed**:

1. Message contains `@your_bot_username` mention.
2. Message is a reply to one of the bot's messages.
3. Message starts with one of `GROUP_TRIGGERS` words (default: `ии,ai,бот,помощник`).

Examples (`GROUP_TRIGGERS=ии,ai,бот,помощник`):

| Group message | Behaviour |
|---|---|
| `AI, What wheater in NY?` | ✅ replies to the answer |
| `Bot, help me with an excercise` | ✅ replies  |
| `@your_bot hi` | ✅ replies to "hi" |
| `hi all!` | ❌ silent |
| `how are you?` | ❌ silent |

The trigger word is configurable via `GROUP_TRIGGERS`, case-insensitive.
A separator after the trigger is required (`AI,`, `AI `, `AI:` work; `AAI` does not).

### Auto-access from groups

Anyone who writes in an allowed group (from `ALLOWED_CHATS`) automatically gets
access to the bot in private chats. No manual addition to `ALLOWED_USERS` needed.
The known-users list is stored in Redis.

## Development

```bash
git clone git@github.com:dolphin2702/tg-ai-bot.git
cd tg-ai-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env
tg-ai-bot
```

## License

MIT
