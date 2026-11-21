import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from applied_jobs import seed_company_portals as seed
from applied_jobs import store


class TrackerTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "applications.sqlite3"

    def make_legacy_tracker(self):
        with sqlite3.connect(self.db) as con:
            con.executescript("""
                CREATE TABLE applications (
                    application_id INTEGER PRIMARY KEY, company_name TEXT, career_page_url TEXT,
                    portal_name TEXT, last_checked_at TEXT, job_id TEXT UNIQUE, job_name TEXT,
                    job_link TEXT, source_portal_url TEXT, applied_at TEXT, questions_answers_json TEXT
                );
                INSERT INTO applications VALUES
                    (1, 'ACME', 'https://acme.test/jobs', 'Acme via ATS', NULL,
                     NULL, '', '', '', '', '[]'),
                    (7, 'ACME', NULL, NULL, NULL, 'R1', 'DEV', 'link', 'source',
                     '2025-09-01T10:00:00Z', '[]');
            """)

    def test_history_reads_preserve_legacy_database_and_labels(self):
        self.make_legacy_tracker()
        before = self.db.read_bytes()
        self.assertTrue(store.check_job_application_status("R1", company_name="acme", database=self.db)["applied"])
        self.assertEqual(len(store.list_applied_jobs_for_company("acme", database=self.db)), 1)
        result = store.query_the_schema(
            "SELECT portal_name, status, status_notes_json FROM applications ORDER BY rowid",
            database=self.db,
        )
        self.assertEqual(result["rows"], [
            {"portal_name": "Acme via ATS", "status": "not_checked", "status_notes_json": "[]"},
            {"portal_name": None, "status": "applied", "status_notes_json": "[]"},
        ])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(list(self.db.parent.iterdir()), [self.db])

    def test_migration_backs_up_legacy_labels_and_keeps_application(self):
        self.make_legacy_tracker()
        store.initialize(self.db)
        store.initialize(self.db)
        backup, = self.db.parent.glob("*.pre-migration-*.sqlite3")
        with sqlite3.connect(backup) as con:
            self.assertEqual(con.execute("SELECT portal_name FROM applications WHERE job_id IS NULL").fetchone()[0],
                             "Acme via ATS")
        with sqlite3.connect(self.db) as con:
            row = con.execute("SELECT * FROM applications WHERE job_id IS NULL").fetchone()
            self.assertEqual(row[:2], ("ACME", "https://acme.test/jobs"))
            self.assertTrue(all(v is None for v in row[2:-2]))
            self.assertEqual(row[-2:], ("not_checked", "[]"))
            job = con.execute("SELECT application_id, applied_at, questions_answers_json FROM applications WHERE job_id = 'R1'")
            self.assertEqual(job.fetchone(), (7, "2025-09-01T10:00:00Z", "[]"))

    def test_employers_can_reuse_an_id_and_retry_without_a_new_application(self):
        def save(name, link):
            return store.save_application(name, "42", [], job_name="Software Engineer",
                                          job_link=link, source_portal_url="source", database=self.db)

        first = save("Acme Labs", "first")
        self.assertFalse(store.check_job_application_status("42", company_name="Beta", database=self.db)["applied"])
        second = save("Beta", "second")
        self.assertNotEqual(first, second)
        self.assertEqual(first, save("acme labs", "updated"))
        for name, link in [("Acme Labs", "updated"), ("Beta", "second")]:
            self.assertEqual(store.check_job_application_status("42", company_name=name, database=self.db),
                             {"applied": True, "job_link": link})
        with self.assertRaisesRegex(ValueError, "company_name"):
            store.check_job_application_status("42", database=self.db)

    def test_supplied_csv_seeds_fresh_database_and_is_repeatable(self):
        with seed.SEED_FILE.open(newline="", encoding="utf-8") as f:
            count = len(list(csv.DictReader(f)))
        self.assertEqual(seed.seed_company_portals(self.db), count)
        self.assertEqual(seed.seed_company_portals(self.db), count)
        with sqlite3.connect(self.db) as con:
            rows = con.execute("SELECT * FROM applications").fetchall()
            self.assertEqual(len({r[0] for r in rows}), count)
            self.assertTrue(all(v is None for row in rows for v in row[2:-2]))
            self.assertTrue(all(row[-2:] == ("not_checked", "[]") for row in rows))

    def test_v2_migration_only_adds_status_columns_and_backfills(self):
        with sqlite3.connect(self.db) as con:
            con.executescript("""
                CREATE TABLE applications (
                    company_name TEXT NOT NULL, career_page_url TEXT, last_checked_at TEXT,
                    application_id INTEGER UNIQUE, job_id TEXT, job_name TEXT, job_link TEXT,
                    source_portal_url TEXT, applied_at TEXT, questions_answers_json TEXT
                        CHECK (questions_answers_json IS NULL OR json_valid(questions_answers_json)),
                    UNIQUE (company_name, job_id)
                );
                CREATE UNIQUE INDEX applications_company_portal_unique
                    ON applications (company_name) WHERE job_id IS NULL;
                PRAGMA user_version = 2;
                INSERT INTO applications (rowid, company_name, career_page_url, last_checked_at)
                    VALUES (16, 'ACME', 'https://acme.test', NULL),
                           (27, 'BETA', 'https://beta.test', '2025-02-01T00:00:00Z');
                INSERT INTO applications (rowid, application_id, company_name, job_id, job_name,
                                          job_link, source_portal_url, applied_at, questions_answers_json)
                    VALUES (42, 7, 'BETA', 'R1', 'DEV', 'link', 'source', '2025-01-02T12:00:00Z',
                            '[{"question":"Role?","answer":"Dev"}]');
            """)
            columns = con.execute("PRAGMA table_info(applications)").fetchall()
            indexes = con.execute("PRAGMA index_list(applications)").fetchall()
            old_rows = con.execute("SELECT rowid, * FROM applications ORDER BY rowid").fetchall()

        store.initialize(self.db)
        store.initialize(self.db)
        with sqlite3.connect(self.db) as con:
            migrated_columns = con.execute("PRAGMA table_info(applications)").fetchall()
            self.assertEqual(migrated_columns[:-2], columns)
            self.assertEqual([c[1] for c in migrated_columns[-2:]], ["status", "status_notes_json"])
            self.assertEqual(con.execute("PRAGMA index_list(applications)").fetchall(), indexes)
            rows = con.execute("SELECT rowid, * FROM applications ORDER BY rowid").fetchall()
            self.assertEqual([row[:-2] for row in rows], old_rows)
            self.assertEqual([row[-2:] for row in rows],
                             [("not_checked", "[]"), ("checked", "[]"), ("applied", "[]")])
        self.assertEqual(len(list(self.db.parent.glob("*.pre-migration-*.sqlite3"))), 1)

    def test_portal_check_and_reseed_track_the_current_url(self):
        url = "https://example.test/jobs"
        store.add_company_portal("Acme", url, database=self.db)
        notes = ["No matching openings"]
        checked_at = store.record_company_portal_check("Acme", status_notes=notes, database=self.db)
        store.add_company_portal("Acme", url, database=self.db)
        query = "SELECT status, last_checked_at, status_notes_json FROM applications WHERE job_id IS NULL"
        with sqlite3.connect(self.db) as con:
            status, timestamp, stored_notes = con.execute(query).fetchone()
            self.assertEqual((status, timestamp, json.loads(stored_notes)), ("checked", checked_at, notes))
        store.add_company_portal("Acme", url + "/new", database=self.db)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute(query).fetchone(), ("not_checked", None, "[]"))

    def test_failed_attempt_can_be_retried_without_overwriting_a_confirmation(self):
        def save(**kwargs):
            return store.save_application("Acme", "R1", [], job_name="Developer", job_link="link",
                                          source_portal_url="source", database=self.db, **kwargs)

        def result():
            with sqlite3.connect(self.db) as con:
                return con.execute("SELECT status, applied_at, status_notes_json FROM applications "
                                   "WHERE company_name = 'ACME' AND job_id = 'R1'").fetchone()

        failure = ["Portal closed before submission"]
        application_id = save(status="failed_to_apply", status_notes=failure)
        status, applied_at, notes = result()
        self.assertEqual((status, applied_at, json.loads(notes)), ("failed_to_apply", None, failure))
        self.assertFalse(store.check_job_application_status("R1", company_name="Acme", database=self.db)["applied"])
        self.assertEqual(store.list_applied_jobs_for_company("Acme", database=self.db), [])

        success = ["Confirmation received"]
        self.assertEqual(save(status_notes=success), application_id)
        status, applied_at, notes = result()
        self.assertEqual((status, json.loads(notes)), ("applied", success))
        self.assertTrue(applied_at)
        self.assertTrue(store.check_job_application_status("R1", company_name="Acme", database=self.db)["applied"])
        self.assertEqual([row["job_id"] for row in store.list_applied_jobs_for_company("Acme", database=self.db)],
                         ["R1"])
        with self.assertRaises(ValueError):
            save(status="failed_to_apply", status_notes=failure)
        self.assertEqual(result(), (status, applied_at, notes))
        earlier_submission = "2025-01-02T12:00:00Z"
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE applications SET applied_at = ? WHERE job_id = 'R1'", (earlier_submission,))
        self.assertEqual(save(), application_id)
        self.assertEqual(result(), ("applied", earlier_submission, notes))

    def test_status_notes_are_bounded_and_failures_need_a_reason(self):
        def save(status, notes):
            return store.save_application("Acme", "R1", [], job_name="Developer", job_link="link",
                                          source_portal_url="source", database=self.db,
                                          status=status, status_notes=notes)

        five = [f"Step {i} failed" for i in range(1, 6)]
        save("failed_to_apply", five)
        for invalid in ([], five + ["Extra"], ["  "], ["First\nSecond"], [2], "One reason"):
            with self.subTest(notes=invalid), self.assertRaises((TypeError, ValueError)):
                save("failed_to_apply", invalid)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(json.loads(con.execute("SELECT status_notes_json FROM applications").fetchone()[0]), five)
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE applications SET status_notes_json = ?", (json.dumps(five + ["Extra"]),))

    def test_legacy_seed_headers(self):
        old = self.db.with_suffix(".csv")
        old.write_text("company_name,career_page_url,portal_name,reported_ctc_lpa,salary_source_url\n"
                       "EXAMPLE,,,16,https://example.test/report\n", encoding="utf-8")
        self.assertEqual(seed.seed_company_portals(self.db, seed_file=old), 1)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT company_name, career_page_url FROM applications").fetchone(),
                             ("EXAMPLE", None))

    def test_current_seed_requires_role_evidence_before_importing(self):
        sample = self.db.with_suffix(".csv")
        sample.write_text(
            "company_name,career_page_url,reported_ctc_lpa,salary_source,engineering_role,role_source\n"
            "FIRST,,18,Graduate offer,Software Engineer,Campus report\n"
            "SECOND,,20,Graduate offer,Software Engineer,\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "role evidence for SECOND"):
            seed.seed_company_portals(self.db, seed_file=sample)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
