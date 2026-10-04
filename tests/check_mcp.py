"""Offline MCP protocol check: isolates account config and never logs into QQ."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    with tempfile.TemporaryDirectory() as directory:
        environment = dict(os.environ)
        environment.pop("QQ_MAIL_ACCOUNT", None)
        environment["XDG_CONFIG_HOME"] = directory
        params = StdioServerParameters(command=sys.executable,
            args=[str(ROOT / "server.py")], env=environment)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {x.name for x in listed.tools} == {"qq_mail_status", "qq_mail_search", "qq_mail_read"}
                assert all(x.annotations.readOnlyHint and x.annotations.destructiveHint is False for x in listed.tools)
                status = await session.call_tool("qq_mail_status", {})
                payload = json.loads(next(x.text for x in status.content if x.type == "text"))
                assert payload["ok"] is False
                assert "Run qq-mail-configure" in payload["error"]
                print("MCP initialization, three read-only tools and missing-account handling passed.")


if __name__ == "__main__":
    asyncio.run(main())
