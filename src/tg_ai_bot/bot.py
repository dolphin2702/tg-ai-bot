import asyncio
import logging
import re
from functools import wraps

from telegram import MessageEntity, Update
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


def _is_reply_to_bot(update: Update, bot_id: int) -> bool:
    msg = update.message
    reply = msg.reply_to_message if msg else None
    if not reply or not reply.from_user:
        return False
    return reply.from_user.id == bot_id


def _has_mention_of(update: Update, username: str) -> bool:
    """Check if the message mentions @username."""
    msg = update.message
    if not msg or not msg.entities or not msg.text:
        return False
    tag = f"@{username.lower()}"
    for ent in msg.entities:
        if ent.type == MessageEntity.MENTION:
            mention = msg.text[ent.offset: ent.offset + ent.length].lower()
            if mention == tag:
                return True
        if ent.type == MessageEntity.TEXT_MENTION and ent.user and ent.user.username:
            if f"@{ent.user.username.lower()}" == tag:
                return True
    return False


def _extract_trigger_prefix(text: str, triggers: list[str]) -> str | None:
    """If ``text`` starts with one of ``triggers`` (case-insensitive) followed
    by a separator, return the remainder. Otherwise return None.

    Examples (triggers = ["ии", "бот"]):
        "ИИ, какая погода"      -> "какая погода"
        "бот: помоги"           -> "помоги"
        "ИИ"                    -> ""
        "иИИИ"                  -> None   (not a word boundary)
        "Просто текст"          -> None
    """
    if not text:
        return None
    stripped = text.lstrip()
    lower = stripped.lower()
    for trig in triggers:
        if not trig:
            continue
        if not lower.startswith(trig):
            continue
        rest = stripped[len(trig):]
        if not rest:
            return ""
        # require a separator right after the trigger
        if rest[0] in " ,:;—–-.!?":
            return rest.lstrip(" ,:;—–-.!?")
    return None


def _authorized(fn):
    """Reject users/chats not authorized by config or seen in allowed groups."""
    @wraps(fn)
    async def wrapper(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self._is_allowed(update):
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
        self._bot_id: int | None = None
        self._bot_username: str | None = None

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

    async def _ensure_bot_info(self) -> None:
        if self._bot_id is None:
            me = await self.app.bot.get_me()
            self._bot_id = me.id
            self._bot_username = me.username or ""

    # ---------- access control ----------

    async def _is_allowed(self, update: Update) -> bool:
        # Dev mode: no restrictions configured
        if not self.cfg.allowed_users and not self.cfg.allowed_chats:
            return True
        user = update.effective_user
        chat = update.effective_chat
        if not user or not chat:
            return False
        # In an allowed group: allow and remember the user for private chats.
        if chat.id in self.cfg.allowed_chats:
            await self.state.mark_known(user.id)
            return True
        # Explicit user allow list (private chats)
        if user.id in self.cfg.allowed_users:
            return True
        # Users seen before in an allowed group
        if await self.state.is_known(user.id):
            return True
        return False

    async def _current(self, user_id: int) -> tuple[str, Engine]:
        name = await self.state.get_engine(user_id, self.cfg.default_engine)
        return name, self.engines[name]

    # ---------- commands ----------

    @_authorized
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await self._ensure_bot_info()
        triggers = ", ".join(self.cfg.group_triggers) if self.cfg.group_triggers else "—"
        await update.message.reply_text(
            "Привет! Я универсальный LLM-бот.\n\n"
            "В личке отвечаю на всё.\n"
            "В группе — только когда обращаются:\n"
            f"  • упоминание @{self._bot_username}\n"
            "  • ответ на моё сообщение\n"
            f"  • или префикс: {triggers}\n\n"
            "Например: «ИИ, какая погода в Самаре»\n\n"
            "Команды:\n"
            "/new — новый диалог\n"
            "/engine — список движков\n"
            "/engine <name> — переключить движок\n"
            "/model — текущая модель\n"
            "/model <name> — сменить модель\n"
            "/system — системный промпт\n"
            "/status — что выбрано сейчас\n"
            "/id — узнать user_id и chat_id\n"
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
            f"user_id: {user.id}\n"
            f"chat_id: {chat.id}\n"
            f"chat type: {chat.type}"
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
                f"Движок {name} управляет системным промптом на своей стороне.\n"
                "Смените промпт в настройках workspace."
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
        msg = update.message
        if not msg:
            return

        await self._ensure_bot_info()
        user_id = update.effective_user.id
        chat = update.effective_chat
        text = msg.text or ""
        is_group = chat.type in ("group", "supergroup")

        # In groups, only respond when directly addressed.
        if is_group:
            mentioned = _has_mention_of(update, self._bot_username or "")
            reply_to_bot = _is_reply_to_bot(update, self._bot_id or 0)
            stripped = _extract_trigger_prefix(text, self.cfg.group_triggers)

            if not (mentioned or reply_to_bot or stripped is not None):
                return  # stay silent

            if stripped is not None:
                text = stripped
            elif mentioned:
                tag = f"@{self._bot_username}"
                text = re.sub(re.escape(tag), "", text, flags=re.IGNORECASE).strip()
            # if it was just a reply with no text, keep original text

            if not text:
                return

        name, engine = await self._current(user_id)

        # System prompt applies only to stateless engines.
        system_prompt: str | None = None
        if not engine.is_stateful():
            system_prompt = await self.state.get_system(user_id) or self.cfg.system_prompt

        if engine.is_stateful():
            # Stateful backends keep history server-side; send only the new message.
            messages = [Message(role="user", content=text)]
        else:
            history = await self.state.get_history(user_id, name)
            history.append({"role": "user", "content": text})
            messages = [Message(role=m["role"], content=m["content"]) for m in history]
            if system_prompt:
                messages = [Message(role="system", content=system_prompt)] + messages

        thread_id = None
        if engine.is_stateful():
            thread_id = await self.state.get_thread(user_id, name)
            if not thread_id:
                try:
                    thread_id = await engine.new_thread()
                    if thread_id:
                        await self.state.set_thread(user_id, name, thread_id)
                except Exception as e:
                    await msg.reply_text(f"❌ Не удалось создать тред: {e}")
                    return

        model = await self.state.get_model(user_id, name)

        placeholder = await msg.reply_text("…")
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

            if not engine.is_stateful():
                history.append({"role": "assistant", "content": final})
                await self.state.set_history(user_id, name, history)

            parts = _chunk(final)
            try:
                await placeholder.edit_text(parts[0])
            except Exception:
                await msg.reply_text(parts[0])
            for extra in parts[1:]:
                await msg.reply_text(extra)

        except Exception as e:
            log.exception("engine.chat failed")
            try:
                await placeholder.edit_text(f"❌ Ошибка: {e}")
            except Exception:
                await msg.reply_text(f"❌ Ошибка: {e}")
