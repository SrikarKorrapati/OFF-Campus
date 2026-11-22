"""Track job sources, company portals, and job applications in SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Preserve package imports for workers that get their tool schemas from database.
if __package__:
    from .tool_definitions import TOOL_DEFINITIONS, WORKER_TOOL_DEFINITIONS

DIRECTORY = Path(__file__).resolve().parent
DATABASE = DIRECTORY / "applications.sqlite3"
SCHEMA = DIRECTORY / "schema.sql"
SCHEMA_VERSION = 7
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SAVE_CHANNEL_CHECKPOINT = """
    INSERT INTO whatsapp_channels (channel_id, last_checked_at) VALUES (?, ?)
    ON CONFLICT (channel_id) DO UPDATE
    SET last_checked_at = max(last_checked_at, excluded.last_checked_at)
"""


def _ensure_schema(connection: sqlite3.Connection, database: Path) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version == 4:
        # SQLite requires rebuilding the table to extend its status CHECK.
        connection.execute("ALTER TABLE applications RENAME TO applications_v4")
        connection.execute("DROP INDEX IF EXISTS applications_company_portal_unique")
    elif version not in (0, 5, 6) or (
        version == 0 and connection.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table'").fetchone()
    ):
        raise ValueError(f"Unsupported tracker schema version {version}. Expected {SCHEMA_VERSION}.")

    for statement in SCHEMA.read_text(encoding="utf-8").split(";"):
        connection.execute(statement)
    if version == 4:
        columns = ", ".join(row[1] for row in connection.execute("PRAGMA table_info(applications)"))
        connection.execute(
            f"INSERT INTO applications (rowid, {columns}) SELECT rowid, {columns} FROM applications_v4"
        )
        connection.execute("DROP TABLE applications_v4")
    legacy = database.parent / "whatsapp_scan" / "last_checked.json"
    if legacy.is_file():
        checkpoints = json.loads(legacy.read_text(encoding="utf-8"))
        connection.executemany(SAVE_CHANNEL_CHECKPOINT, checkpoints.items())
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def _read_history(database: Path):
    """Open the tracker read-only, using empty in-memory history before the first write."""
    exists = database.is_file() and database.stat().st_size > 0
    location = f"{database.resolve().as_uri()}?mode=ro" if exists else ":memory:"
    with closing(sqlite3.connect(location, uri=True)) as connection:
        if not exists:
            connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        connection.execute("PRAGMA query_only = ON")
        yield connection


@contextmanager
def _write(database: Path):
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema(connection, database)
        yield connection


def initialize(database: Path = DATABASE) -> Path:
    """Create or upgrade the tracker in a single transaction."""
    with _write(database):
        return database


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime(UTC_FORMAT)


def whatsapp_channel_checkpoint(
    channel_id: str, started: datetime, *, complete: bool = False, database: Path = DATABASE
) -> str:
    """Return the channel's UTC cutoff, saving the scan start only on completion."""
    with _write(database) as connection:
        if complete:
            connection.execute(SAVE_CHANNEL_CHECKPOINT, (channel_id, started.strftime(UTC_FORMAT)))
        row = connection.execute(
            "SELECT last_checked_at FROM whatsapp_channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()
    return row[0] if row else (started - timedelta(days=14)).strftime(UTC_FORMAT)


def record_job_portal_scan(portal_id: int, scan_started_at: str, *, database: Path = DATABASE) -> str:
    """Record a completed scan's UTC start and return the latest saved timestamp."""
    started = datetime.strptime(scan_started_at, UTC_FORMAT).strftime(UTC_FORMAT)
    with _write(database) as connection:
        row = connection.execute("""
            UPDATE job_portals SET last_accessed_at = max(coalesce(last_accessed_at, ''), ?)
            WHERE id = ? RETURNING last_accessed_at
        """, (started, portal_id)).fetchone()
        if row is None:
            raise ValueError(f"Unknown job portal ID: {portal_id}")
        return row[0]


def normalize_name(name: str) -> str:
    """Store company and job names in uppercase with underscores between words."""
    return "_".join(name.split()).upper()


def _encode_status_notes(notes: list[str] | None) -> str | None:
    if notes is None:
        return None
    if not isinstance(notes, list):
        raise TypeError("status_notes must be a list of bullet points")
    if len(notes) > 5:
        raise ValueError("status_notes accepts at most five bullet points")
    bullets = []
    for note in notes:
        if not isinstance(note, str) or len(note.strip().splitlines()) != 1:
            raise ValueError("Each status note must be one nonblank line of text")
        bullets.append(note.strip())
    return json.dumps(bullets, ensure_ascii=False)


def add_company_portal(
    company_name: str, career_page_url: str | None = None, *, database: Path = DATABASE
) -> None:
    """Register an employer. A new or changed careers URL starts unchecked."""
    company_name = normalize_name(company_name)
    career_page_url = (career_page_url or "").strip() or None
    if not company_name:
        raise ValueError("company_name is required")
    if career_page_url and not career_page_url.startswith(("https://", "http://")):
        raise ValueError("career_page_url must be an HTTP or HTTPS URL")

    with _write(database) as connection:
        connection.execute(
            """
            INSERT INTO applications (company_name, career_page_url) VALUES (?, ?)
            ON CONFLICT (company_name) WHERE job_id IS NULL DO UPDATE SET
                career_page_url = excluded.career_page_url,
                last_checked_at = NULL, status = 'not_checked', status_notes_json = '[]'
            WHERE excluded.career_page_url IS NOT NULL
              AND excluded.career_page_url IS NOT applications.career_page_url
            """,
            (company_name, career_page_url),
        )


def record_company_portal_check(
    company_name: str, *, status_notes: list[str] | None = None, database: Path = DATABASE
) -> str:
    """Mark a careers portal checked and optionally record notes about the check."""
    company_name = normalize_name(company_name)
    if not company_name:
        raise ValueError("company_name is required")
    encoded_notes = _encode_status_notes(status_notes)
    checked_at = _utc_now()
    with _write(database) as connection:
        result = connection.execute(
            """
            UPDATE applications
            SET last_checked_at = ?, status = 'checked',
                status_notes_json = COALESCE(?, CASE WHEN status = 'checked' THEN status_notes_json ELSE '[]' END)
            WHERE company_name = ? AND job_id IS NULL AND career_page_url IS NOT NULL
            """,
            (checked_at, encoded_notes, company_name),
        )
        if result.rowcount == 0:
            raise ValueError("Add the company's careers page before recording a check")
    return checked_at


def claim_job(company_name: str, job_id: str, *, database: Path = DATABASE) -> dict[str, bool | str]:
    """Claim a new or previously failed opening for one application worker."""
    key = (normalize_name(company_name), job_id.strip())
    if not all(key):
        raise ValueError("company_name and job_id are required")

    with _write(database) as connection:
        result = connection.execute("""
            INSERT INTO applications (application_id, company_name, job_id, status)
            VALUES ((SELECT coalesce(max(application_id), 0) + 1 FROM applications), ?, ?, 'in_progress')
            ON CONFLICT (company_name, job_id) DO UPDATE SET status = 'in_progress'
            WHERE applications.status = 'failed_to_apply'
        """, key)
        if result.rowcount:
            return {"claimed": True, "status": "in_progress"}
        status, = connection.execute(
            "SELECT status FROM applications WHERE company_name = ? AND job_id = ?", key
        ).fetchone()
        return {"claimed": False, "status": status}


def save_application(
    company_name: str,
    job_id: str,
    questions_answers: list[dict[str, Any]],
    *,
    job_name: str,
    job_link: str,
    source_portal_url: str,
    status: str = "applied",
    status_notes: list[str] | None = None,
    database: Path = DATABASE,
) -> int:
    """Record a confirmed submission or a failed attempt for a specific opening."""
    company_name = normalize_name(company_name)
    job_id = job_id.strip()
    job_name = normalize_name(job_name)
    job_link = job_link.strip()
    source_portal_url = source_portal_url.strip()
    if not all((company_name, job_id, job_name, job_link, source_portal_url)):
        raise ValueError(
            "company_name, job_id, job_name, job_link, and source_portal_url are required"
        )
    if not isinstance(questions_answers, list):
        raise TypeError("questions_answers must be a list")
    if any(
        not isinstance(item, dict) or "question" not in item or "answer" not in item
        for item in questions_answers
    ):
        raise ValueError("Each item must contain question and answer fields")

    if status not in ("applied", "failed_to_apply"):
        raise ValueError("Job status must be applied or failed_to_apply")
    encoded_notes = _encode_status_notes(status_notes)
    if status == "failed_to_apply" and not status_notes:
        raise ValueError("A failed attempt requires at least one reason in status_notes")
    values = {
        "company": company_name, "job_id": job_id, "name": job_name, "link": job_link,
        "source": source_portal_url, "answers": json.dumps(questions_answers, ensure_ascii=False),
        "status": status, "notes": encoded_notes or "[]",
        "applied_at": _utc_now() if status == "applied" else None,
    }
    with _write(database) as connection:
        previous = connection.execute(
            "SELECT application_id, status, applied_at, status_notes_json FROM applications "
            "WHERE company_name = :company AND job_id = :job_id", values,
        ).fetchone()
        if previous is None:
            return connection.execute("""
                INSERT INTO applications (application_id, company_name, job_id, job_name, job_link,
                    source_portal_url, questions_answers_json, status, status_notes_json, applied_at)
                VALUES ((SELECT coalesce(max(application_id), 0) + 1 FROM applications),
                    :company, :job_id, :name, :link, :source, :answers, :status, :notes, :applied_at)
                RETURNING application_id
            """, values).fetchone()[0]

        application_id, old_status, submitted_at, old_notes = previous
        if old_status == "applied":
            if status == "failed_to_apply":
                raise ValueError("This application is already confirmed and cannot be marked failed")
            values["applied_at"] = submitted_at
        if status == old_status and status_notes is None:
            values["notes"] = old_notes
        connection.execute("""
            UPDATE applications SET job_name = :name, job_link = :link, source_portal_url = :source,
                questions_answers_json = :answers, status = :status, status_notes_json = :notes,
                applied_at = :applied_at WHERE company_name = :company AND job_id = :job_id
        """, values)
        return application_id


def query_the_schema(
    sql_query: str, *, parameters: tuple[Any, ...] = (), database: Path = DATABASE
) -> dict[str, Any]:
    """Run one read-only SQLite query and return its columns and result rows."""
    if not isinstance(sql_query, str):
        raise TypeError("sql_query must be a string")
    sql_query = sql_query.strip()
    if not re.match(r"^(SELECT|WITH|PRAGMA|EXPLAIN)\b", sql_query, re.IGNORECASE):
        raise ValueError("sql_query must be one read-only SELECT, WITH, PRAGMA, or EXPLAIN query")

    try:
        with _read_history(database) as connection:
            cursor = connection.execute(sql_query, parameters)
            if cursor.description is None:
                raise ValueError("sql_query must return rows")
            columns = [column[0] for column in cursor.description]
            rows = [
                {
                    column: value.hex() if isinstance(value, bytes) else value
                    for column, value in zip(columns, row)
                }
                for row in cursor.fetchall()
            ]
    except sqlite3.Error as error:
        raise ValueError(f"SQL query failed: {error}") from error
    return {"columns": columns, "rows": rows}


TOOL_HANDLERS = {"query_the_schema": query_the_schema}
WORKER_TOOL_HANDLERS = {**TOOL_HANDLERS, "claim_job": claim_job}


if __name__ == "__main__":
    print(initialize())
