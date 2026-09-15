from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.store import DATA, ROOT, Store


class KnowledgeClient:
    """One task owns SDK contexts. Calls from jobs are queued into that task."""

    def __init__(self, store: Store):
        self.store = store
        self.queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.tools = []
        self.error = None
        self.task = None
        self.connected = False

    async def start(self):
        self.task = asyncio.create_task(self._serve())
        await asyncio.wait_for(self.ready.wait(), timeout=30)

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _serve(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "backend.mcp_server"], cwd=str(ROOT), env={**os.environ, "EXAMPILOT_DATA_DIR": str(self.store.directory), "PYTHONIOENCODING": "utf-8"})
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=45)) as session:
                    await session.initialize()
                    self.tools = (await session.list_tools()).tools
                    if {t.name for t in self.tools} != {"search", "get_chunk_context"}:
                        raise RuntimeError("MCP 工具发现不完整")
                    self.connected = True
                    self.error = None
                    self.ready.set()
                    while True:
                        name, args, future = await self.queue.get()
                        if future.cancelled():
                            continue
                        try:
                            result = await session.call_tool(name, args)
                            if result.isError:
                                raise RuntimeError("; ".join(c.text for c in result.content if hasattr(c, "text")))
                            data = result.structuredContent
                            if data is None:
                                data = json.loads(next(c.text for c in result.content if hasattr(c, "text")))
                            if not future.done():
                                future.set_result(data)
                        except Exception as exc:
                            if not future.done():
                                future.set_exception(RuntimeError(str(exc)[:500]))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)[:300]
        finally:
            self.connected = False
            self.ready.set()
            while not self.queue.empty():
                _, _, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(RuntimeError("MCP 连接已关闭"))

    async def call(self, name, args, job_id="system", agent_role="generation"):
        if not self.connected:
            raise RuntimeError("知识检索 MCP 未连接，请在设置页重连")
        future = asyncio.get_running_loop().create_future()
        started = time.monotonic()
        await self.queue.put((name, args, future))
        try:
            result = await asyncio.wait_for(future, timeout=120)
            self.store.event(job_id, "tool_called", {"tool": name, "agent_role": agent_role, "transport": "stdio", "status": "ok", "arguments": args, "result_ids": [r.get("id", r.get("query_id")) for r in result.get("results", [])], "duration_ms": round((time.monotonic() - started) * 1000)})
            return result
        except Exception:
            self.store.event(job_id, "tool_called", {"tool": name, "agent_role": agent_role, "transport": "stdio", "status": "error", "duration_ms": round((time.monotonic() - started) * 1000)})
            raise

    def health(self):
        return {"connected": self.connected, "tools": [t.name for t in self.tools], "transport": "stdio", "error": self.error}
