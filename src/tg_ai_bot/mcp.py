import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


@dataclass
class MCPTool:
    server: str
    name: str
    description: str
    input_schema: dict

    def to_openai(self) -> dict:
        """Convert to OpenAI tools API format."""
        return {
            "type": "function",
            "function": {
                "name": f"{self.server}__{self.name}",
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


class MCPClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def list_tools(self, url: str) -> list[dict]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result", {}).get("tools", [])

    async def call_tool(self, url: str, name: str, arguments: dict) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        if "error" in data:
            msg = data["error"].get("message") if isinstance(data["error"], dict) else data["error"]
            return f"ERROR: {msg}"
        content = data.get("result", {}).get("content", [])
        parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(parts) if parts else "(no content)"


class MCPRegistry:
    """Holds all tools from all configured MCP servers."""

    def __init__(self, servers: dict[str, str]):
        self.servers = servers          # name -> url
        self.client = MCPClient()
        self.tools: list[MCPTool] = []

    async def load(self) -> None:
        """Fetch tool lists from every configured server."""
        self.tools = []
        for name, url in self.servers.items():
            try:
                raw = await self.client.list_tools(url)
                for t in raw:
                    self.tools.append(MCPTool(
                        server=name,
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                    ))
                log.info("MCP %s: loaded %d tools", name, len(raw))
            except Exception as e:
                log.error("MCP %s: failed to load tools: %s", name, e)

    def openai_tools(self) -> list[dict]:
        return [t.to_openai() for t in self.tools]

    def find(self, qualified_name: str) -> MCPTool | None:
        """Find a tool by its OpenAI-qualified name ``server__tool``."""
        for t in self.tools:
            if f"{t.server}__{t.name}" == qualified_name:
                return t
        return None

    async def call(self, qualified_name: str, arguments: dict) -> str:
        t = self.find(qualified_name)
        if not t:
            return f"ERROR: unknown tool {qualified_name}"
        url = self.servers[t.server]
        try:
            return await self.client.call_tool(url, t.name, arguments)
        except Exception as e:
            return f"ERROR: {e}"
