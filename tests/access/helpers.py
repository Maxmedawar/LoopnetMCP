"""Client helpers shared by the access-control tests."""

from fastmcp import Client


async def tool_names(mcp) -> set[str]:
    """Names visible through tools/list for the current identity."""
    async with Client(mcp) as client:
        return {tool.name for tool in await client.list_tools()}


async def call_data(mcp, tool: str, args: dict | None = None):
    """Call a tool through the middleware and return its deserialized data."""
    async with Client(mcp) as client:
        result = await client.call_tool(tool, args or {})
        return result.data
