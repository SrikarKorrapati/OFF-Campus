import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tracker import daily_scan
from job_tracker.codex_session import SessionResult
from job_tracker.database import initialize
from job_tracker.scan_sources import PORTAL_URLS


class DailyScanTest(unittest.IsolatedAsyncioTestCase):
    start = "2026-11-22T09:00:00Z"
    old = "2026-11-01T09:00:00Z"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = initialize(Path(temporary.name) / "applications.sqlite3")
        self.db = sqlite3.connect(path, isolation_level=None)
        self.addCleanup(self.db.close)
        for setting in (patch.object(daily_scan, "DATABASE", path),
                        patch.object(daily_scan.sources, "utc_now", return_value=self.start)):
            setting.start()
            self.addCleanup(setting.stop)

    async def test_sources_run_once_in_phase_order_and_only_complete_scans_advance(self):
        self.db.executemany("""
            INSERT INTO applications (company_name, career_page_url, status, last_checked_at)
            VALUES (?, 'https://employer.example/jobs', ?, ?)
        """, [("NEW", "not_checked", None), ("DUE", "checked", self.old), ("RECENT", "checked", self.start)])
        self.db.execute("UPDATE job_portals SET last_accessed_at=? WHERE name IN ('Wellfound','WhatsApp')",
                        (self.old,))
        self.db.execute("INSERT INTO whatsapp_channels VALUES ('partial', ?)", (self.old,))
        companies = {"NEW", "DUE"}
        boards = set(PORTAL_URLS) - {"WhatsApp"}
        finished = []

        async def session(instructions, task, *, output_schema):
            self.assertEqual(task["scan_start"], self.start)
            report = {"problem": None, "worker_ids": []}
            if "company_name" in task:
                name = task["company_name"]
                report["careers_url"] = task["career_page_url"]
                if name == "DUE":
                    report["problem"] = "Last page would not load"
            elif "name" in task:
                name = task["name"]
                self.assertTrue(companies.issubset(finished))
                self.assertEqual(task["url"], PORTAL_URLS[name])
                self.assertEqual(task["cutoff"], self.old if name == "Wellfound" else "2026-11-08T09:00:00Z")
            else:
                name = "WhatsApp"
                self.assertTrue(boards.issubset(finished))
                self.assertEqual(task["first_cutoff"], "2026-11-08T09:00:00Z")
                self.assertEqual(task["channel_cutoffs"], {"partial": self.old})
                report = {"problem": None, "channels": [
                    {"channel_id": "new", "problem": None, "worker_ids": []},
                    {"channel_id": "partial", "problem": "History unavailable", "worker_ids": []},
                ]}
            await asyncio.sleep(0)
            finished.append(name)
            return SessionResult(report, {}, True)

        with patch.object(daily_scan, "run_codex_session", side_effect=session):
            results = await daily_scan.run_daily_scan()
        self.assertCountEqual(finished, [*companies, *PORTAL_URLS])
        self.assertEqual({r["source"] for r in results if r["problems"]}, {"DUE", "WhatsApp"})
        self.assertEqual(dict(self.db.execute("SELECT company_name, last_checked_at FROM applications")),
                         {"NEW": self.start, "DUE": self.old, "RECENT": self.start})
        self.assertEqual(dict(self.db.execute("SELECT name, last_accessed_at FROM job_portals")),
                         {**dict.fromkeys(boards, self.start), "WhatsApp": self.old})
        self.assertEqual(dict(self.db.execute("SELECT channel_id, last_checked_at FROM whatsapp_channels")),
                         {"new": self.start, "partial": self.old})

    async def test_reported_workers_and_submissions_must_match_native_ids_and_tracker(self):
        self.db.execute("DELETE FROM job_portals WHERE name NOT IN ('Wellfound','Indeed','Shine')")
        self.db.execute("UPDATE job_portals SET last_accessed_at=?", (self.old,))
        self.db.execute("""
            INSERT INTO applications (company_name, job_id, status, job_name, job_link,
                source_portal_url, questions_answers_json, applied_at)
            VALUES ('ACME', '123', 'applied', 'ENGINEER', 'https://acme.example/jobs/123',
                    ?, '[]', ?)
        """, (PORTAL_URLS["Wellfound"], self.old))

        async def session(instructions, task, *, output_schema):
            name = task["name"]
            job_id = "missing" if name == "Indeed" else "123"
            outcome = {"listing_url": f"https://acme.example/jobs/{job_id}", "status": "applied",
                       "company_name": "Acme", "job_id": job_id, "reason": None}
            worker_id = f"worker-{name}"
            reported = "different-worker" if name == "Shine" else worker_id
            return SessionResult({"problem": None, "worker_ids": [reported]}, {worker_id: json.dumps(outcome)}, True)

        with patch.object(daily_scan, "run_codex_session", side_effect=session):
            results = await daily_scan.run_daily_scan()
        problems = {r["source"]: r["problems"] for r in results}
        self.assertEqual(problems["Wellfound"], [])
        self.assertIn("tracker", problems["Indeed"][0])
        self.assertIn("job workers", problems["Shine"][0])
        self.assertEqual(dict(self.db.execute("SELECT name, last_accessed_at FROM job_portals")),
                         {"Wellfound": self.start, "Indeed": self.old, "Shine": self.old})

    async def test_missing_browser_halts_queued_sources_without_advancing_checkpoints(self):
        reply = SessionResult({"problem": None, "worker_ids": []}, {}, False)
        with patch.object(daily_scan, "run_codex_session", return_value=reply) as launch:
            results = await daily_scan.run_daily_scan()
        self.assertLessEqual(launch.await_count, daily_scan.MAX_SOURCE_SESSIONS)
        self.assertTrue(results[-1]["problems"])
        self.assertEqual(self.db.execute("SELECT count(last_accessed_at) FROM job_portals").fetchone(), (0,))
