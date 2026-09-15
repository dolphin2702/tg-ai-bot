import asyncio
import logging
import re
from functools import wraps

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Config
from .engines import Engine, Message
from .state import State

log = logging.getLogger(__name__)

EDIT_THROTTLE = 1.0       # seconds between message edits while streaming
TG_LIMIT = 4000           # Telegram per-message limit


def _strip_tags(s: str) -> str:
    """Remove XML-ish tool tags that some backends leave in the output."""
    s = re.sub(r"<[^>]+>", "", s)
    return "\n".join(line for line in s.splitlines() if line.strip())


def _chunk(text: str, size: int = TG_LIMIT) -> list[str]:
    if not text:
        return [""]
    return [text[i:i + size] for i in range(0, len(text), size)]


def _authorized(fn):
    """Reject users/chats not present in ALLOWED_USERS / ALLOWED_CHATS."""
    @wraps(fn)
    async def wrapper(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            u = update.effective_user
            c = update.effective_chat
            log.warning(
                "Unauthorized access: user_id=%s chat_id=%s",
                u.id if u else "?", c.id if c else "?",
            )
            return
        return await fn(self, update, ctx)
    return wrapper


class Bot:
    def __init__(self, cfg: Config, state: State, engines: dict[str, Engine]):
        self.cfg = cfg
        self.state = state
        self.engines = engines
        self.app: Application | None = None

    # ---------- access control ----------

    def _is_allowed(self, update: Update) -> bool:
        # Dev mode: no restrictions configured
        if not self.cfg.allowed_users and not self.cfg.allowed_chats:
            return True
        user = update.effective_user
        chat = update.effective_chat
        if user and user.id in self.cfg.allowed_users:
            return True
        if chat and chat.id in self.cfg.allowed_chats:
            return True
        return False

    # ---------- setup ----------

    def build(self) -> Application:
        app = Application.builder().token(self.cfg.telegram_token).build()
        app.add_handler(CommandHandler("start",  self.cmd_start))
        app.add_handler(CommandHandler("help",   self.cmd_help))
        app.add_handler(CommandHandler("id",     self.cmd_id))
        app.add_handler(CommandHandler("new",    self.cmd_new))
        app.add_handler(CommandHandler("engine", self.cmd_engine))
        app.add_handler(CommandHandler("model",  self.cmd_model))
        app.add_handler(CommandHandler("system", self.cmd_system))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))
        self.app = app
        return app

    async def _current(self, user_id: int) -> tuple[str, Engine]:
        name = await self.state.get_engine(user_id, self.cfg.default_engine)
        return name, self.engines[name]

    # ---------- commands ----------

    @_authorized
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Привет! Я универсальный LLM-бот.\n\n"
            "Команды:\n"
            "/new — новый диалог\n"
            "/engine — список движков\n"
            "/engine <name> — переключить движок\n"
            "/model — текущая модель\n"
            "/model <name> — сменить модель\n"
            "/system — системный промпт\n"
            "/status — что выбрано сейчас\n"
            "/id — узнать свой user_id и chat_id\n"
            "/help — помощь"
        )

    @_authorized
    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await self.cmd_start(update, ctx)

    @_authorized
    async def cmd_id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat = update.effective_chat
        await update.message.reply_text(
            f"user_id: `{user.id}`\n"
            f"chat_id: `{chat.id}`\n"
            f"chat type: {chat.type}",
            parse_mode="Markdown",
        )

    @_authorized
    async def cmd_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        name, engine = await self._current(user_id)
        await self.state.clear_history(user_id, name)
        if engine.is_stateful():
            await self.state.clear_thread(user_id, name)
            try:
                tid = await engine.new_thread()
                if tid:
                    await self.state.set_thread(user_id, name, tid)
            except Exception as e:
                await update.message.reply_text(f"⚠️ Не удалось создать тред: {e}")
                return
        await update.message.reply_text("✅ Новый диалог начат.")

    @_authorized
    async def cmd_engine(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        args = ctx.args or []
        if not args:
            cur, _ = await self._current(user_id)
            lines = ["Доступные движки:"]
            for name in self.engines:
                marker = "▶️" if name == cur else "  "
                lines.append(f"{marker} {name}")
            lines.append("\nПереключить: /engine <name>")
            await update.message.reply_text("\n".join(lines))
            return
        name = args[0].lower()
        if name not in self.engines:
            await update.message.reply_text(f"❌ Нет движка {name}")
            return
        await self.state.set_engine(user_id, name)
        await update.message.reply_text(f"✅ Движок: {name}")

    @_authorized
    async def cmd_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        name, engine = await self._current(user_id)
        args = ctx.args or []
        if not args:
            cur = await self.state.get_model(user_id, name) or getattr(engine, "model", "—")
            await update.message.reply_text(
                f"Модель ({name}): {cur}\nСменить: /model <name>"
            )
            return
        await self.state.set_model(user_id, name, args[0])
        await update.message.reply_text(f"✅ Модель: {args[0]}")

    @_authorized
    async def cmd_system(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        name, engine = await self._current(user_id)

        if engine.is_stateful():
            await update.message.reply_text(
                f"Движок `{name}` управляет системным промптом на своей стороне.\n"
                "Смените промпт в настройках workspace.",
                parse_mode="Markdown",
            )
            return

        args = ctx.args or []
        if not args:
            cur = await self.state.get_system(user_id) or self.cfg.system_prompt
            preview = cur if len(cur) < 500 else cur[:500] + "…"
            await update.message.reply_text(
                f"Текущий системный промпт:\n\n{preview}\n\n"
                "Команды:\n"
                "/system <текст> — задать свой\n"
                "/system reset — вернуть дефолт"
            )
            return

        if args[0].lower() == "reset":
            await self.state.clear_system(user_id)
            await update.message.reply_text("✅ Промпт сброшен на дефолт.")
            return

        prompt = " ".join(args)
        await self.state.set_system(user_id, prompt)
        await update.message.reply_text(
            f"✅ Системный промпт сохранён ({len(prompt)} символов).\n"
            "Применится со следующего сообщения."
        )

    @_authorized
    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        name, engine = await self._current(user_id)
        model = await self.state.get_model(user_id, name) or getattr(engine, "model", "—")
        stateful = "да" if engine.is_stateful() else "нет"
        if not engine.is_stateful():
            sys_prompt = await self.state.get_system(user_id) or self.cfg.system_prompt
            sys_info = f"Системный промпт: {len(sys_prompt)} символов"
        else:
            sys_info = "Системный промпт: управляется движком"
        await update.message.reply_text(
            f"Движок: {name}\n"
            f"Модель: {model}\n"
            f"Stateful: {stateful}\n"
            f"{sys_info}"
        )

    # ---------- message handler ----------

    @_authorized
    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text or ""
        name, engine = await self._current(user_id)

        # System prompt applies only to stateless engines.
        system_prompt: str | None = None
        if not engine.is_stateful():
            system_prompt = await self.state.get_system(user_id) or self.cfg.system_prompt

        # Build the message list depending on engine type.
        if engine.is_stateful():
            # Stateful backends keep history server-side; send only the new message.
            messages = [Message(role="user", content=text)]
        else:
            history = await self.state.get_history(user_id, name)
            history.append({"role": "user", "content": text})
            messages = [Message(role=m["role"], content=m["content"]) for m in history]
            if system_prompt:
                messages = [Message(role="system", content=system_prompt)] + messages

        # Thread for stateful engines.
        thread_id = None
        if engine.is_stateful():
            thread_id = await self.state.get_thread(user_id, name)
            if not thread_id:
                try:
                    thread_id = await engine.new_thread()
                    if thread_id:
                        await self.state.set_thread(user_id, name, thread_id)
                except Exception as e:
                    await update.message.reply_text(f"❌ Не удалось создать тред: {e}")
                    return

        model = await self.state.get_model(user_id, name)

        placeholder = await update.message.reply_text("…")
        buffer = ""
        last_edit = 0.0
        loop = asyncio.get_event_loop()

        try:
            async for chunk in engine.chat(messages, thread_id=thread_id, model=model):
                buffer += chunk
                now = loop.time()
                if now - last_edit >= EDIT_THROTTLE and len(buffer) <= TG_LIMIT:
                    try:
                        await placeholder.edit_text(buffer or "…")
                    except Exception:
                        pass
                    last_edit = now

            final = _strip_tags(buffer).strip() or "(пустой ответ)"

            # Persist history only for stateless engines.
            if not engine.is_stateful():
                history.append({"role": "assistant", "content": final})
                await self.state.set_history(user_id, name, history)

            parts = _chunk(final)
            try:
                await placeholder.edit_text(parts[0])
            except Exception:
                await update.message.reply_text(parts[0])
            for extra in parts[1:]:
                await update.message.reply_text(extra)

        except Exception as e:
            log.exception("engine.chat failed")
            try:
                await placeholder.edit_text(f"❌ Ошибка: {e}")
            except Exception:
                await update.message.reply_text(f"❌ Ошибка: {e}")
