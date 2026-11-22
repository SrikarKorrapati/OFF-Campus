"""Look up application history or call the project's tracker MCP server."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from .history import get_company_status, has_applied_to_company, list_recently_applied_companies


async def run_mcp(tool: str | None, arguments: dict) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(
        command=sys.executable, args=["-m", "job_tracker.mcp_server"],
        cwd=Path(__file__).resolve().parents[1],
    )
    async with stdio_client(server) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        if tool is None:
            catalog = await session.list_tools()
            print(json.dumps([item.model_dump(include={"name", "description", "inputSchema"})
                              for item in catalog.tools], ensure_ascii=False, indent=2))
            return 0
        reply = await session.call_tool(tool, arguments)
        for item in reply.content:
            if item.type == "text":
                print(item.text, file=sys.stderr if reply.isError else sys.stdout)
        return int(reply.isError)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recent = commands.add_parser("recent", help="List companies applied to in the last HOURS hours")
    recent.add_argument("hours", type=float, metavar="HOURS")
    applied = commands.add_parser("applied", help="Check whether an application was submitted to COMPANY")
    applied.add_argument("company", metavar="COMPANY")
    status = commands.add_parser("status", help="Show the tracker status for COMPANY")
    status.add_argument("company", metavar="COMPANY")
    mcp = commands.add_parser("mcp", help="List tracker MCP tools or call one with JSON from stdin")
    mcp.add_argument("tool", nargs="?", help="Tool name; omit to list available tools")

    args = parser.parse_args()
    try:
        if args.command == "mcp":
            arguments = json.load(sys.stdin) if args.tool else {}
            if not isinstance(arguments, dict):
                parser.error("MCP arguments must be a JSON object")
            raise SystemExit(asyncio.run(run_mcp(args.tool, arguments)))
        if args.command == "recent":
            result = list_recently_applied_companies(args.hours)
        elif args.command == "applied":
            result = has_applied_to_company(args.company)
        else:
            result = get_company_status(args.company)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
