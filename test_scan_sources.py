import sqlite3
import tempfile
import unittest
from pathlib import Path

from job_tracker.database import table_sql
from job_tracker.scan_sources import (
    PORTAL_URLS, channel_checkpoints, complete_channel, complete_company, complete_portal,
    due_companies, first_cutoff, list_portals,
)


class ScanSourcesTest(unittest.TestCase):
    early = "2026-10-31T18:31:08Z"
    start = "2026-11-14T18:31:08Z"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / "tracker.sqlite3"

    def company(self, name, url=None, stamp=None):
        table_sql("applications", """
            INSERT INTO applications (company_name, career_page_url, status, last_checked_at)
            VALUES (?, ?, ?, ?)
        """, (name, url, "checked" if stamp else "not_checked", stamp), database=self.db)

    def test_due_companies_at_the_exact_72_hour_boundary(self):
        self.company("New")
        self.company("Due", "https://due.example", "2026-11-11T18:31:08Z")
        self.company("Later", "https://later.example", "2026-11-11T18:31:09Z")
        table_sql("applications", """
            INSERT INTO applications (company_name, job_id, status) VALUES ('LEGACY', '123', 'in_progress')
        """, database=self.db)
        self.assertEqual([row["company_name"] for row in due_companies(self.start, database=self.db)],
                         ["NEW", "DUE"])

    def test_only_a_completed_company_scan_updates_its_verified_url(self):
        original = "https://old.example/jobs"
        verified = "https://employer.example/jobs"
        self.company("Correct Co", original, self.early)
        for url in ("", "https://", "unsupported"):
            with self.assertRaises(ValueError):
                complete_company("Correct Co", original, url, self.start, database=self.db)
        self.assertEqual(due_companies(self.start, database=self.db)[0]["last_checked_at"], self.early)
        complete_company("Correct Co", original, verified, self.start, database=self.db)
        complete_company("Correct Co", original, verified, self.early, database=self.db)
        with self.assertRaisesRegex(ValueError, "changed"):
            complete_company("Correct Co", original, "https://other.example", self.start, database=self.db)
        with self.assertRaisesRegex(ValueError, "changed"):
            complete_company("Correct Co", verified, "https://other.example", self.early, database=self.db)
        self.assertEqual(table_sql("applications", """
            SELECT status, career_page_url, last_checked_at FROM applications
        """, database=self.db)["rows"], [
            {"status": "checked", "career_page_url": verified, "last_checked_at": self.start}
        ])
        self.company("Missing Link")
        complete_company("Missing Link", None, verified, self.start, database=self.db)
        self.assertEqual(due_companies(self.start, database=self.db), [])

    def test_url_change_rolls_back_if_marking_complete_fails(self):
        self.company("Employer", "https://old.example", self.early)
        with sqlite3.connect(self.db) as connection:
            connection.execute("""CREATE TRIGGER simulate_failure BEFORE UPDATE ON applications
                WHEN NEW.status = 'checked' BEGIN SELECT RAISE(ABORT, 'interrupted'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "interrupted"):
            complete_company("Employer", "https://old.example", "https://new.example",
                             self.start, database=self.db)
        self.assertEqual(due_companies(self.start, database=self.db), [
            {"company_name": "EMPLOYER", "career_page_url": "https://old.example", "last_checked_at": self.early}
        ])

    def test_source_list_and_independent_monotonic_checkpoints(self):
        portals = list_portals(self.start, database=self.db)
        self.assertEqual({row["name"]: row["url"] for row in portals}, PORTAL_URLS)
        self.assertTrue(all(row["cutoff"] == self.early for row in portals))
        self.assertEqual(channel_checkpoints(database=self.db), {})
        self.assertEqual(first_cutoff(self.start), self.early)
        self.assertFalse(self.db.exists())

        first_id = portals[0]["id"]
        complete_portal(first_id, self.start, database=self.db)
        complete_portal(first_id, self.early, database=self.db)
        complete_channel("channel", self.start, database=self.db)
        complete_channel("channel", self.early, database=self.db)
        self.assertEqual(channel_checkpoints(database=self.db), {"channel": self.start})
        after = list_portals(self.start, database=self.db)
        self.assertEqual(after[0]["cutoff"], self.start)
        self.assertEqual(after[1:], portals[1:])
        with self.assertRaisesRegex(ValueError, "Unknown portal"):
            complete_portal(-1, self.start, database=self.db)
        with self.assertRaises(ValueError):
            complete_channel("channel", "2026-11-14", database=self.db)
