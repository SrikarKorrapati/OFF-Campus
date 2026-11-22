import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from job_tracker.database import claim_job, table_sql


class TrackerToolsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "tracker.sqlite3"

    def sql(self, table, query, *values, **options):
        return table_sql(table, query, values, database=self.db, **options)

    def test_scope_read_only_and_cleanup(self):
        def applications(query, **options):
            return self.sql("applications", query, **options)

        self.assertEqual(applications("SELECT count(*) AS n FROM applications")["rows"], [{"n": 0}])
        self.assertFalse(self.db.exists())
        with self.assertRaises(ValueError):
            applications("INSERT INTO applications(company_name) VALUES ('TEST')", read_only=True)
        with self.assertRaises(ValueError):
            applications("WITH names AS (SELECT name FROM job_portals) SELECT * FROM names")
        with self.assertRaises(ValueError):
            applications("UPDATE job_portals SET name='Wrong' WHERE id=1")
        self.assertEqual(applications("SELECT * FROM applications")["rows"], [])
        self.sql("applications", "INSERT INTO applications(company_name) VALUES (?)", "Test Co")
        with self.assertRaises(ValueError):
            applications("DELETE FROM applications")
        with self.assertRaises(ValueError):
            applications("INSERT OR REPLACE INTO applications(company_name) VALUES ('TEST_CO')")
        with self.assertRaises(ValueError):
            applications("INSERT OR IGNORE INTO applications(company_name) VALUES ('Test Co')")
        self.assertEqual(applications("SELECT company_name FROM applications")["rows"],
                         [{"company_name": "TEST_CO"}])
        self.assertEqual(applications("DELETE FROM applications WHERE company_name='TEST_CO'", cleanup=True)["affected"], 1)

    def test_confirmed_application_keeps_its_identity_and_timestamp(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: claim_job(" Test  Co ", "15", database=self.db), range(4)))
        self.assertEqual(sum(claim["claimed"] for claim in claims), 1)
        self.assertTrue(claim_job("Another Co", "15", database=self.db)["claimed"])
        self.sql("applications", """UPDATE applications SET job_name=?, status='applied',
            source_portal_url='WhatsApp', job_link='https://example.org/jobs/15', questions_answers_json='[]'
            WHERE company_name=normalize_name(?) AND job_id=?""", "Software Engineer", "Test Co", "15")
        select = "SELECT job_name, applied_at FROM applications WHERE company_name='TEST_CO'"
        row, = self.sql("applications", select)["rows"]
        self.assertEqual(row["job_name"], "SOFTWARE_ENGINEER")
        self.assertRegex(row["applied_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.sql("applications", "UPDATE applications SET status_notes_json=? WHERE company_name='TEST_CO'", '["Receipt"]')
        for field in ("applied_at=NULL", "status='failed_to_apply'", "job_id='another'"):
            with self.assertRaises(ValueError):
                self.sql("applications", f"UPDATE applications SET {field} WHERE company_name='TEST_CO'")
        self.assertEqual(self.sql("applications", select)["rows"], [row])

    def test_question_history_can_search_individual_answers(self):
        claim_job("Example", "15", database=self.db)
        self.sql("applications", "UPDATE applications SET questions_answers_json=? WHERE job_id=?",
                 '[{"question":"Availability?", "answer":"Six months"}]', "15")
        result = self.sql("applications", """SELECT json_extract(answer.value,'$.answer') AS answer
            FROM applications, json_each(questions_answers_json) AS answer
            WHERE json_extract(answer.value,'$.question')=?""", "Availability?", read_only=True)
        self.assertEqual(result["rows"], [{"answer": "Six months"}])

    def test_checkpoints_preserve_the_latest_successful_scan(self):
        early, late = "2026-11-20T10:00:00Z", "2026-11-22T10:00:00Z"
        for table, key, stamp in (("job_portals", "name", "last_accessed_at"),
                                  ("whatsapp_channels", "channel_id", "last_checked_at")):
            self.sql(table, f"INSERT INTO {table} ({key}, {stamp}) VALUES (?, ?)", "example", late)
            with self.assertRaises(ValueError):
                self.sql(table, f"UPDATE {table} SET {stamp}=? WHERE {key}=?", early, "example")
            self.assertEqual(self.sql(table, f"SELECT {stamp} FROM {table} WHERE {key}=?", "example")["rows"],
                             [{stamp: late}])
            self.assertEqual(self.sql(table, f"DELETE FROM {table} WHERE {key}=?", "example", cleanup=True)["affected"], 1)


if __name__ == "__main__":
    unittest.main()
