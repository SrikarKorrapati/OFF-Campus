"""Expose the three application-history lookups over local MCP stdio."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .history import get_company_status, has_applied_to_company, list_recently_applied_companies

server = FastMCP("job-tracker")
read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
for lookup in (list_recently_applied_companies, has_applied_to_company, get_company_status):
    server.add_tool(lookup, annotations=read_only)


if __name__ == "__main__":
    server.run(transport="stdio")
