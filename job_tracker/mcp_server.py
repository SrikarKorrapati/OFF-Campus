"""Serve the tracker and application question tools over MCP stdio."""

from mcp.server.fastmcp import FastMCP

from . import database
from .tool_definitions import register_mcp_tools

server = FastMCP("job-tracker")
register_mcp_tools(server)


if __name__ == "__main__":
    database.initialize()
    server.run(transport="stdio")
