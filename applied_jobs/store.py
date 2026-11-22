"""Track company portals and job applications in one SQLite table."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
DATABASE = DIRECTORY / "applications.sqlite3"
SCHEMA = DIRECTORY / "schema.sql"
SCHEMA_VERSION = 4


def initialize(database: Path = DATABASE) -> Path:
    """Create an empty tracker or use an existing tracker with the current schema."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        version, has_tables = connection.execute(
            "SELECT user_version, EXISTS(SELECT 1 FROM sqlite_schema WHERE type = 'table') "
            "FROM pragma_user_version"
        ).fetchone()
        if version == SCHEMA_VERSION:
            return database
        if version or has_tables:
            raise ValueError(f"Unsupported tracker schema version {version}. Expected {SCHEMA_VERSION}.")
        schema = SCHEMA.read_text(encoding="utf-8")
        connection.executescript(f"BEGIN IMMEDIATE;\n{schema}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    return database


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
    initialize(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        yield connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    sql_query: str, *, database: Path = DATABASE
) -> dict[str, Any]:
    """Run one read-only SQLite query and return its columns and result rows."""
    if not isinstance(sql_query, str):
        raise TypeError("sql_query must be a string")
    sql_query = sql_query.strip()
    if not re.match(r"^(SELECT|WITH|PRAGMA|EXPLAIN)\b", sql_query, re.IGNORECASE):
        raise ValueError("sql_query must be one read-only SELECT, WITH, PRAGMA, or EXPLAIN query")

    try:
        with _read_history(database) as connection:
            cursor = connection.execute(sql_query)
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


TOOL_DEFINITIONS = [
    {
        "name": "query_the_schema",
        "description": (
            "Run one read-only SQLite query and return the columns and rows. "
            "CREATE TABLE applications (company_name TEXT, career_page_url TEXT, last_checked_at TEXT, "
            "application_id INTEGER, job_id TEXT, job_name TEXT, job_link TEXT, source_portal_url TEXT, "
            "applied_at TEXT, questions_answers_json TEXT, status TEXT, status_notes_json TEXT). "
            "Company rows have NULL job_id and status 'not_checked' or 'checked'. "
            "Job attempts are keyed by company_name and job_id. Count confirmed submissions with "
            "status = 'applied'. A failed attempt is 'failed_to_apply'. Names are uppercase with "
            "underscores. Timestamps are ISO 8601 UTC. career_page_url is the employer's portal, "
            "job_link is the opening, and source_portal_url is where it was found. "
            "The JSON lists hold question/answer objects and up to five status notes, respectively."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql_query": {
                    "type": "string",
                    "description": (
                        "One read-only SQLite query that returns rows, such as "
                        "SELECT job_id, job_name FROM applications "
                        "WHERE status = 'applied' LIMIT 10"
                    ),
                }
            },
            "required": ["sql_query"],
            "additionalProperties": False,
        },
    },
]

TOOL_HANDLERS = {"query_the_schema": query_the_schema}


if __name__ == "__main__":
    print(initialize())
