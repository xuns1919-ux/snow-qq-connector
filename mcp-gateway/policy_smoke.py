"""Offline policy smoke tests for the restricted SnowLuma MCP deployment."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


async def main() -> None:
    assert server.ENABLE_GENERIC_ACTIONS is False
    denied = await server.call_snowluma("set_group_kick", {"group_id": 1, "user_id": 2})
    assert denied["ok"] is False
    assert "not allowed" in denied["error"]

    mcp = server.build_snowluma_mcp()
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "call_onebot_action" not in names
    print("GENERIC_ACTIONS=DISABLED")
    print("HIGH_RISK_DENY=PASS")
    print("GENERIC_TOOL_NOT_REGISTERED=PASS")
    print(f"TOOL_COUNT={len(names)}")


if __name__ == "__main__":
    asyncio.run(main())
