"""Small local SQLite store for company portals and job applications."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


DIRECTORY = Path(__file__).resolve().parent
DATABASE = DIRECTORY / "applications.sqlite3"
SCHEMA = DIRECTORY / "schema.sql"
SCHEMA_VERSION = 3


@contextmanager
def _read_database(database: Path):
    """Read an existing database as-is. A new tracker has empty in-memory history."""
    if database.is_file() and database.stat().st_size:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(":memory:")
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    with closing(connection):
        connection.execute("PRAGMA query_only = ON")
        yield connection


@contextmanager
def _read_history(database: Path):
    with _read_database(database) as source:
        source.execute("BEGIN")
        columns = [row[1] for row in source.execute("PRAGMA table_info(applications)")]
        if "status" in columns or "job_id" not in columns:
            yield source
            return

        # Expose the new fields on old databases without changing their files or backups.
        with closing(sqlite3.connect(":memory:")) as snapshot:
            source.backup(snapshot)
            source.rollback()
            _add_status_columns(snapshot, columns)
            snapshot.execute("PRAGMA query_only = ON")
            yield snapshot


def _back_up_database(database: Path) -> None:
    """Keep a complete, uniquely named snapshot before replacing a legacy table."""
    with NamedTemporaryFile(dir=database.parent, prefix=f"{database.name}.pre-migration-",
                            suffix=".sqlite3", delete=False) as backup:
        path = Path(backup.name)
    try:
        with _read_database(database) as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


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


def _company_portal_values(company_name: str, career_page_url: str | None) -> tuple[str, str | None]:
    company_name = normalize_name(company_name)
    career_page_url = (career_page_url or "").strip() or None
    if not company_name:
        raise ValueError("company_name is required")
    if career_page_url and not career_page_url.startswith(("https://", "http://")):
        raise ValueError("career_page_url must be an HTTP or HTTPS URL")
    return company_name, career_page_url


def add_company_portals(
    companies: Iterable[tuple[str, str | None]], *, database: Path = DATABASE
) -> None:
    """Import company rows in one transaction. New or changed links start unchecked."""
    values = [_company_portal_values(name, url) for name, url in companies]
    initialize(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executemany(
            """
            INSERT INTO applications (
                company_name, career_page_url
            ) VALUES (?, ?)
            ON CONFLICT (company_name) WHERE job_id IS NULL DO UPDATE SET
                career_page_url = excluded.career_page_url,
                last_checked_at = NULL, status = 'not_checked', status_notes_json = '[]'
            WHERE excluded.career_page_url IS NOT NULL
              AND excluded.career_page_url IS NOT applications.career_page_url
            """,
            values,
        )


def add_company_portal(
    company_name: str, career_page_url: str | None = None, *, database: Path = DATABASE
) -> None:
    """Register one employer and its optional careers URL."""
    add_company_portals([(company_name, career_page_url)], database=database)


def record_company_portal_check(
    company_name: str, *, status_notes: list[str] | None = None, database: Path = DATABASE
) -> str:
    """Mark a careers portal checked and optionally record notes about the check."""
    company_name = normalize_name(company_name)
    if not company_name:
        raise ValueError("company_name is required")
    encoded_notes = _encode_status_notes(status_notes)
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    initialize(database)
    with closing(sqlite3.connect(database)) as connection, connection:
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


def _backfill_statuses(connection: sqlite3.Connection, *, has_check_time: bool = True) -> None:
    checked = "WHEN NULLIF(last_checked_at, '') IS NOT NULL THEN 'checked'" if has_check_time else ""
    connection.execute(f"""
        UPDATE applications SET status = CASE
            WHEN job_id IS NOT NULL THEN 'applied'
            {checked}
            ELSE 'not_checked'
        END
    """)


def _add_status_columns(connection: sqlite3.Connection, old_columns: Iterable[str]) -> None:
    connection.execute("""
        ALTER TABLE applications ADD COLUMN status TEXT NOT NULL DEFAULT 'not_checked'
            CHECK (status IN ('not_checked', 'checked', 'applied', 'failed_to_apply'))
    """)
    # Existing job rows need their outcome before SQLite validates the row-kind check.
    _backfill_statuses(connection, has_check_time="last_checked_at" in old_columns)
    # SQLite disallows subqueries in CHECK constraints. Check each possible bullet.
    note_values = [f"json_extract(status_notes_json, '$[{i}]')" for i in range(5)]
    bullets = " AND ".join(
        f"coalesce(json_type(status_notes_json, '$[{i}]') = 'text' "
        f"AND trim({value}, char(9, 32)) <> '', 1)"
        for i, value in enumerate(note_values)
    )
    connection.execute(f"""
        ALTER TABLE applications ADD COLUMN status_notes_json TEXT NOT NULL DEFAULT '[]'
            CHECK (CASE WHEN json_valid(status_notes_json) THEN
                (job_id IS NULL) = (status IN ('not_checked', 'checked'))
                AND json_type(status_notes_json) = 'array'
                AND json_array_length(status_notes_json) BETWEEN (status = 'failed_to_apply') AND 5
                AND {bullets}
                AND printf('%s%s%s%s%s', {', '.join(note_values)})
                    NOT GLOB ('*[' || char(10, 11, 12, 13, 28, 29, 30, 133, 8232, 8233) || ']*')
            ELSE 0 END)
    """)


def initialize(database: Path = DATABASE) -> Path:
    """Install the single-table schema, upgrading earlier layouts atomically."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return database
        if version > SCHEMA_VERSION:
            raise ValueError("This database uses a newer application schema")
        old_columns = [r[1] for r in connection.execute("PRAGMA table_info(applications)")]
        old_portals = list(connection.execute("PRAGMA table_info(company_portal_checks)"))
        if old_columns or old_portals:
            _back_up_database(database)
        if version == 2:
            _add_status_columns(connection, old_columns)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return database
        if old_columns:
            connection.execute("ALTER TABLE applications RENAME TO previous_applications")
            connection.execute("DROP INDEX IF EXISTS applications_company_portal_unique")

        # executescript would commit the open migration before running the DDL.
        for statement in SCHEMA.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                connection.execute(statement)

        if old_columns:
            # Preserve the public application ID and its underlying rowid on submitted jobs.
            job_fields = ["application_id", "company_name", "job_id", "job_name",
                          "job_link", "source_portal_url", "applied_at", "questions_answers_json",
                          "career_page_url", "last_checked_at"]
            available = [c for c in job_fields if c in old_columns or c == "application_id"]
            fields = ", ".join(available)
            values = {c: c for c in available}
            values["application_id"] = ("COALESCE(application_id, rowid)" if "application_id" in old_columns
                                        else "rowid")
            for c in ("career_page_url", "last_checked_at"):
                if c in values:
                    values[c] = f"NULLIF({c}, '')"
            connection.execute(
                f"INSERT INTO applications (rowid, {fields}, status) "
                f"SELECT rowid, {', '.join(values.values())}, 'applied' "
                "FROM previous_applications WHERE job_id IS NOT NULL"
            )

        for table in ("previous_applications", "company_portal_checks"):
            columns = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
            if not columns:
                continue
            fields = ["company_name"]
            fields.extend(c for c in ("career_page_url", "last_checked_at") if c in columns)
            projection = ", ".join(fields)
            values = ", ".join(f"NULLIF({c}, '')" if c != "company_name" else c for c in fields)
            condition = " WHERE job_id IS NULL" if "job_id" in columns else ""
            connection.execute(
                f"INSERT INTO applications ({projection}) SELECT {values} FROM {table}{condition}"
            )
            connection.execute(f"DROP TABLE {table}")
        if old_columns or old_portals:
            _backfill_statuses(connection)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return database


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
    encoded_answers = json.dumps(questions_answers, ensure_ascii=False)
    applied_at = None
    if status == "applied":
        applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    initialize(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            INSERT INTO applications (
                application_id, company_name, job_id, job_name, job_link,
                source_portal_url, applied_at, questions_answers_json, status, status_notes_json
            ) VALUES ((SELECT COALESCE(MAX(application_id), 0) + 1 FROM applications),
                      :company, :job_id, :name, :link, :source, :applied_at, :answers, :status, COALESCE(:notes, '[]'))
            ON CONFLICT (company_name, job_id) DO UPDATE SET
                job_name = excluded.job_name,
                job_link = excluded.job_link,
                source_portal_url = excluded.source_portal_url,
                questions_answers_json = excluded.questions_answers_json,
                applied_at = CASE WHEN applications.status = 'applied'
                                  THEN applications.applied_at ELSE excluded.applied_at END,
                status = excluded.status,
                status_notes_json = COALESCE(:notes, CASE WHEN applications.status = excluded.status
                                                          THEN applications.status_notes_json ELSE '[]' END)
            WHERE applications.status <> 'applied' OR excluded.status = 'applied'
            RETURNING application_id
            """,
            {"company": company_name, "job_id": job_id, "name": job_name, "link": job_link,
             "source": source_portal_url, "applied_at": applied_at, "answers": encoded_answers,
             "status": status, "notes": encoded_notes},
        ).fetchone()
        if row is None:
            raise ValueError("This application is already confirmed and cannot be marked failed")
    return int(row[0])


def list_applied_jobs_for_company(
    company: str, *, database: Path = DATABASE
) -> list[dict[str, str]]:
    """List saved applications for a company; an empty list means none are recorded."""
    company = normalize_name(company)
    if not company:
        raise ValueError("company is required")
    with _read_history(database) as connection:
        columns = {r[1] for r in connection.execute("PRAGMA table_info(applications)")}
        source = "source_portal_url" if "source_portal_url" in columns else "NULL"
        time = "applied_at" if "applied_at" in columns else "NULL"
        rows = connection.execute(
            f"""
            SELECT job_name, job_id, job_link, {source}, {time}
            FROM applications
            WHERE company_name = ? AND job_id IS NOT NULL AND status = 'applied'
            ORDER BY job_name, job_id
            """,
            (company,),
        ).fetchall()
    return [
        {
            "job_name": row[0],
            "job_id": row[1],
            "job_link": row[2],
            "source_portal_url": row[3],
            "applied_at": row[4],
        }
        for row in rows
    ]


def check_job_application_status(
    job_id: str, *, company_name: str | None = None, database: Path = DATABASE
) -> dict[str, Any]:
    """Look up a requisition within an employer. Ambiguous ID-only lookups need a name."""
    job_id = job_id.strip()
    if not job_id:
        raise ValueError("job_id is required")
    sql = "SELECT status, job_link FROM applications WHERE job_id = ?"
    parameters = [job_id]
    if company_name is not None:
        company_name = normalize_name(company_name)
        if not company_name:
            raise ValueError("company_name is required")
        sql += " AND company_name = ?"
        parameters.append(company_name)
    with _read_history(database) as connection:
        rows = connection.execute(sql + " LIMIT 2", parameters).fetchall()
    if len(rows) > 1:
        raise ValueError("Multiple employers use this job_id. Supply company_name.")
    if not rows or rows[0][0] != "applied":
        return {"applied": False}
    return {"applied": True, "job_link": rows[0][1]}


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
            "Query local application history with one read-only SQLite statement. "
            "Returns columns and rows, with each row keyed by column name. "
            "Company rows have a NULL job_id and status 'not_checked' or 'checked'. "
            "Job attempts have status 'applied' or 'failed_to_apply'. Filter on "
            "status = 'applied' when counting submissions or checking for duplicates. "
            "status_notes_json is a JSON array of up to five brief notes about the status. "
            "To identify a specific application, match both "
            "company_name and job_id because employers can reuse requisition IDs. "
            "Company and job names are uppercase with underscores between words. "
            "applied_at is the submission time in ISO 8601 UTC. last_checked_at is "
            "the time of the last careers page check. questions_answers_json is an "
            "array of objects with question and answer fields.\n\n"
            + SCHEMA.read_text(encoding="utf-8").strip()
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
