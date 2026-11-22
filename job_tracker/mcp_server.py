"""Expose the three scoped SQL tools and the atomic job claim over MCP stdio."""

from mcp.server.fastmcp import FastMCP

from . import database
from .tool_definitions import register_mcp_tools

server = FastMCP("job-tracker")
register_mcp_tools(server)


if __name__ == "__main__":
    database.initialize()
    server.run(transport="stdio")
