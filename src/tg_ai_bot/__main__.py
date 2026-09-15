import logging

from .bot import Bot
from .config import load_config
from .engines import build_engine
from .mcp import MCPRegistry
from .state import State


async def _on_startup(app) -> None:
    """Load MCP tools inside the running event loop."""
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

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

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
