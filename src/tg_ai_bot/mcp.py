import json
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "tg-ai-bot"
CLIENT_VERSION = "0.2.7"


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


class MCPServerSession:
    """One long-lived session per MCP server.

    Implements the Streamable HTTP transport per spec:
    https://modelcontextprotocol.io/specification/2025-03-26/basic/transports

    Steps:
      1. POST initialize → server returns ``Mcp-Session-Id`` header.
      2. POST notifications/initialized (no id) → server returns 202.
      3. Every subsequent request carries ``Mcp-Session-Id``.
      4. On shutdown, DELETE the session URL.
    """

    def __init__(self, name: str, url: str, timeout: float = 60.0):
        self.name = name
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict:
        h = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _capture_session_id(self, resp: httpx.Response) -> None:
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid

    def _parse_response(self, resp: httpx.Response) -> dict:
        """Return the JSON-RPC response object.

        The server may reply with either application/json or text/event-stream.
        For SSE we collect all ``data:`` lines and return the last object that
        has an ``id`` (i.e. the actual response, not notifications).
        """
        ctype = (resp.headers.get("content-type") or "").lower()
        if "text/event-stream" in ctype:
            return self._parse_sse(resp.text)
        # 202 Accepted with no body (for notifications).
        if resp.status_code == 202 or not resp.content:
            return {}
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _parse_sse(text: str) -> dict:
        result: dict = {}
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "id" in obj:
                result = obj
        return result

    async def open(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, read=None),
        )
        # 1. initialize
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
        resp = await self._client.post(self.url, json=body, headers=self._headers())
        resp.raise_for_status()
        self._capture_session_id(resp)
        data = self._parse_response(resp)
        if "error" in data:
            raise RuntimeError(f"MCP initialize error: {data['error']}")
        if self.session_id:
            log.info("MCP %s: session %s", self.name, self.session_id[:8])
        # 2. notifications/initialized (no id, no reply expected)
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            await self._client.post(self.url, json=notif, headers=self._headers())
        except Exception as e:
            log.debug("MCP %s: initialized notification failed: %s", self.name, e)

    async def close(self) -> None:
        if not self._client:
            return
        if self.session_id:
            try:
                await self._client.delete(self.url, headers=self._headers())
            except Exception:
                pass
        await self._client.aclose()
        self._client = None

    async def _call(self, method: str, params: dict | None = None) -> dict:
        if not self._client:
            raise RuntimeError(f"MCP {self.name}: session not open")
        body: dict = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            body["params"] = params
        resp = await self._client.post(self.url, json=body, headers=self._headers())
        resp.raise_for_status()
        self._capture_session_id(resp)
        return self._parse_response(resp)

    async def list_tools(self) -> list[dict]:
        data = await self._call("tools/list")
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> str:
        data = await self._call("tools/call", {"name": name, "arguments": arguments})
        if "error" in data:
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            return f"ERROR: {msg}"
        content = data.get("result", {}).get("content", [])
        parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(parts) if parts else "(no content)"


class MCPRegistry:
    """Holds one MCPServerSession per configured server and all loaded tools."""

    def __init__(self, servers: dict[str, str]):
        self.servers = servers          # name -> url
        self.sessions: dict[str, MCPServerSession] = {}
        self.tools: list[MCPTool] = []

    async def load(self) -> None:
        """Open sessions and fetch tool lists from every configured server."""
        if self.sessions:
            log.warning("MCP registry already loaded, skipping")
            return
        self.tools = []
        for name, url in self.servers.items():
            session = MCPServerSession(name, url)
            try:
                await session.open()
                raw = await session.list_tools()
                for t in raw:
                    self.tools.append(MCPTool(
                        server=name,
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema",
                                            {"type": "object", "properties": {}}),
                    ))
                self.sessions[name] = session
                log.info("MCP %s: loaded %d tools", name, len(raw))
            except Exception as e:
                log.error("MCP %s: failed to load tools: %s", name, e)
                try:
                    await session.close()
                except Exception:
                    pass

    async def close(self) -> None:
        for session in self.sessions.values():
            try:
                await session.close()
            except Exception:
                pass
        self.sessions.clear()

    def openai_tools(self) -> list[dict]:
        return [t.to_openai() for t in self.tools]

    def find(self, qualified_name: str) -> MCPTool | None:
        for t in self.tools:
            if f"{t.server}__{t.name}" == qualified_name:
                return t
        return None

    async def call(self, qualified_name: str, arguments: dict) -> str:
        t = self.find(qualified_name)
        if not t:
            return f"ERROR: unknown tool {qualified_name}"
        session = self.sessions.get(t.server)
        if not session:
            return f"ERROR: no active session for {t.server}"
        try:
            return await session.call_tool(t.name, arguments)
        except Exception as e:
            return f"ERROR: {e}"
