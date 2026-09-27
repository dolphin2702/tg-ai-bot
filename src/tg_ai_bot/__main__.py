import logging
import logging.handlers
import os
from pathlib import Path

from .bot import Bot
from .config import load_config
from .engines import build_engine
from .mcp import MCPRegistry
from .state import State


LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB
LOG_BACKUPS = int(os.environ.get("LOG_BACKUPS", "5"))


def _setup_logging() -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    # File with rotation — best-effort; if the directory is not writable,
    # skip file logging and stay with console only.
    try:
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(file_handler)
    except Exception as e:
        logging.getLogger(__name__).warning(
            "File logging disabled: %s", e
        )

    # Quieter third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.INFO)


async def _on_startup(app) -> None:
    cfg = app.bot_data["cfg"]
    mcp: MCPRegistry | None = app.bot_data.get("mcp")
    if mcp is None:
        return
    logging.info("MCP servers: %s", list(cfg.mcp_servers))
    await mcp.load()
    logging.info("MCP tools loaded: %d", len(mcp.tools))


async def _on_shutdown(app) -> None:
    mcp: MCPRegistry | None = app.bot_data.get("mcp")
    if mcp:
        await mcp.close()


def main() -> None:
    _setup_logging()

    cfg = load_config()
    engines = {name: build_engine(ec) for name, ec in cfg.engines.items()}
    state = State(cfg.redis_url, history_limit=cfg.history_limit)

    mcp = MCPRegistry(cfg.mcp_servers) if cfg.mcp_servers else None

    bot = Bot(cfg, state, engines, mcp=mcp)
    app = bot.build()
    app.bot_data["cfg"] = cfg
    app.bot_data["mcp"] = mcp
    app.post_init = _on_startup
    app.post_shutdown = _on_shutdown

    logging.info("Engines: %s", list(engines))
    logging.info("Default engine: %s", cfg.default_engine)
    logging.info("Log dir: %s", LOG_DIR)

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
