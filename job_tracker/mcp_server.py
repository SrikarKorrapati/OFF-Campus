"""Expose the three scoped SQL tools and the atomic job claim over MCP stdio."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import database
from .tool_definitions import TABLES

server = FastMCP("job-tracker")


def register_table(table: str) -> None:
    @server.tool(name=f"{table}_sql", description=(
        f"Query or edit only {table}. " + TABLES[table] +
        " Send one SELECT, WITH ... SELECT, INSERT, UPDATE, or DELETE. Bind values to ? with "
        "parameters. Results contain columns and rows, plus affected for writes. Set cleanup=true "
        "only for a DELETE explicitly requested by the user."
    ), annotations=ToolAnnotations(openWorldHint=False, destructiveHint=True))
    def run_sql(sql_query: str, parameters: list[database.SQLValue] | None = None,
                cleanup: bool = False) -> dict:
        return database.table_sql(table, sql_query, parameters or [], cleanup=cleanup)


for table_name in TABLES:
    register_table(table_name)


@server.tool(annotations=ToolAnnotations(openWorldHint=False, destructiveHint=False))
def claim_job(company_name: str, job_id: str) -> dict:
    """Reserve an employer requisition before applying. Only the worker receiving claimed=true proceeds."""
    return database.claim_job(company_name, job_id)


if __name__ == "__main__":
    database.initialize()
    server.run(transport="stdio")
