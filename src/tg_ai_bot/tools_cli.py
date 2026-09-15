import asyncio
import logging

from .config import load_config
from .mcp import MCPRegistry


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    if not cfg.mcp_servers:
        print("No MCP servers configured.")
        print("Set MCP_<NAME>_URL in .env, e.g.:")
        print("  MCP_SEARCH_URL=https://searxng.example.com/mcp")
        return
    print(f"Configured servers: {list(cfg.mcp_servers)}")
    reg = MCPRegistry(cfg.mcp_servers)
    await reg.load()
    print()
    if not reg.tools:
        print("No tools loaded. Check server URLs and logs above.")
        return
    for t in reg.tools:
        print(f"[{t.server}] {t.name}")
        print(f"    {t.description[:120]}")
        params = (t.input_schema or {}).get("properties", {})
        if params:
            print(f"    args: {', '.join(params)}")
        print()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
