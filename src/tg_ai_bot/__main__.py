import asyncio
import logging

from .bot import Bot
from .config import load_config
from .engines import build_engine
from .mcp import MCPRegistry
from .state import State


async def _load_mcp(cfg) -> MCPRegistry | None:
    if not cfg.mcp_servers:
        return None
    reg = MCPRegistry(cfg.mcp_servers)
    await reg.load()
    return reg


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    cfg = load_config()
    engines = {name: build_engine(ec) for name, ec in cfg.engines.items()}
    state = State(cfg.redis_url, history_limit=cfg.history_limit)

    # Load MCP tools before building the bot.
    mcp = asyncio.run(_load_mcp(cfg))
    if mcp:
        logging.info("MCP servers: %s", list(cfg.mcp_servers))
        logging.info("MCP tools loaded: %d", len(mcp.tools))
    else:
        logging.info("MCP disabled (no servers configured)")

    bot = Bot(cfg, state, engines, mcp=mcp)
    app = bot.build()

    logging.info("Engines: %s", list(engines))
    logging.info("Default engine: %s", cfg.default_engine)

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()