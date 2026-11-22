import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ReportingTest(unittest.IsolatedAsyncioTestCase):
    async def test_public_interfaces_read_the_same_history(self):
        with tempfile.TemporaryDirectory() as directory:
            # Both entry points resolve the database beside the package they run from.
            source = Path(__file__).resolve().parent / "job_tracker"
            package = Path(directory) / "job_tracker"
            package.mkdir()
            for path in [*source.glob("*.py"), source / "schema.sql"]:
                shutil.copy(path, package)
            database = package / "applications.sqlite3"

            def cli(*args):
                return subprocess.check_output(
                    [sys.executable, "-m", "job_tracker.cli", *args], cwd=directory, text=True
                )

            server = StdioServerParameters(
                command=sys.executable, args=["-m", "job_tracker.mcp_server"], cwd=directory
            )
            async with stdio_client(server) as (reader, writer), ClientSession(reader, writer) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                self.assertSetEqual({tool.name for tool in tools}, {
                    "list_recently_applied_companies", "has_applied_to_company", "get_company_status",
                })
                self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
                commands = re.search(r"\{([^}]+)\}", cli("--help")).group(1).split(",")
                self.assertCountEqual(commands, ["recent", "applied", "status"])

                async def check(command, value, tool, arguments):
                    reply = await session.call_tool(tool, arguments)
                    self.assertFalse(reply.isError, reply.content)
                    result = json.loads(cli(command, value))
                    structured = result if isinstance(result, dict) else {"result": result}
                    self.assertEqual(reply.structuredContent, structured)
                    return result

                recent = ("recent", "24", "list_recently_applied_companies", {"hours": 24})
                self.assertEqual(await check(*recent), [])
                self.assertFalse(database.exists())

                with closing(sqlite3.connect(database)) as connection, connection:
                    connection.executescript((package / "schema.sql").read_text())
                    connection.executescript("""
                        INSERT INTO applications (company_name, job_id, status, applied_at) VALUES
                        ('SAMPLE_CO', '1', 'applied', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour')),
                        ('SAMPLE_CO', '2', 'applied', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-4 hours')),
                        ('ANOTHER_CO', '1', 'applied', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-2 hours')),
                        ('OLDER_CO', '3', 'applied', strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-3 days')),
                        ('OTHER_CO', NULL, 'not_checked', NULL),
                        ('OTHER_CO', '4', 'failed_to_apply', NULL),
                        ('OTHER_CO', '5', 'in_progress', NULL);
                    """)
                snapshot = database.read_bytes()
                self.assertEqual(await check(*recent), ["SAMPLE_CO", "ANOTHER_CO"])
                for name, expected in [("sample co", True), ("older co", True), ("other co", False)]:
                    applied = await check("applied", name, "has_applied_to_company", {"company_name": name})
                    self.assertIs(applied, expected)
                status = await check("status", "other co", "get_company_status", {"company_name": "other co"})
                self.assertEqual(status["portal"]["status"], "not_checked")
                self.assertEqual({job["job_id"]: job["status"] for job in status["applications"]},
                                 {"4": "failed_to_apply", "5": "in_progress"})
                self.assertEqual(database.read_bytes(), snapshot)
