"""Serve read-only application history over local MCP stdio."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .history import get_company_status, has_applied_to_company, list_recently_applied_companies

server = FastMCP("job-tracker")
for query in (list_recently_applied_companies, has_applied_to_company, get_company_status):
    server.add_tool(query, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))


if __name__ == "__main__":
    server.run(transport="stdio")
