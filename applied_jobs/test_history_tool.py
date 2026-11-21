import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from applied_jobs import store


class HistoryToolTest(unittest.TestCase):
    def test_agent_exposes_one_read_only_sql_tool_for_application_history(self):
        self.assertEqual([tool["name"] for tool in store.TOOL_DEFINITIONS], ["query_the_schema"])
        self.assertEqual(set(store.TOOL_HANDLERS), {"query_the_schema"})
        query = store.TOOL_HANDLERS["query_the_schema"]

        with tempfile.TemporaryDirectory() as directory:
            database = store.initialize(Path(directory) / "applications.sqlite3")
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "INSERT INTO applications (company_name, job_id, applied_at) VALUES (?, ?, ?)",
                    ("ACME", "R1", "2025-09-01T10:00:00Z"),
                )
            result = query(
                sql_query="SELECT job_id, applied_at FROM applications "
                          "WHERE company_name = 'ACME' AND job_id IS NOT NULL",
                database=database,
            )
            self.assertEqual(result, {
                "columns": ["job_id", "applied_at"],
                "rows": [{"job_id": "R1", "applied_at": "2025-09-01T10:00:00Z"}],
            })
            with self.assertRaises(ValueError):
                query(sql_query="DELETE FROM applications", database=database)
