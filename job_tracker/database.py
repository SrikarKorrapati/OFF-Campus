"""Track job sources, company portals, and job applications in SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

DIRECTORY = Path(__file__).resolve().parent
DATABASE = DIRECTORY / "applications.sqlite3"
SCHEMA = DIRECTORY / "schema.sql"
SCHEMA_VERSION = 7
SQLValue = str | int | float | None
JobStatus = Literal["applied", "failed_to_apply", "in_progress"]
CHECKPOINTS = {"job_portals": "last_accessed_at", "whatsapp_channels": "last_checked_at"}
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


def normalize_name(name: str) -> str:
    """Store company and job names in uppercase with underscores between words."""
    return "_".join(name.split()).upper()


def claim_job(company_name: str, job_id: str, *, database: Path = DATABASE) -> dict[str, bool | str]:
    """Register the verified employer and claim a new or previously failed opening."""
    key = (normalize_name(company_name), job_id.strip())
    if not all(key):
        raise ValueError("company_name and job_id are required")

    with _write(database) as connection:
        connection.execute("""
            INSERT INTO applications (company_name) VALUES (?)
            ON CONFLICT (company_name) WHERE job_id IS NULL DO NOTHING
        """, (key[0],))
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


def _valid_list(value: str | None, answers: bool) -> bool:
    try:
        items = json.loads(value) if value is not None else None
    except (TypeError, ValueError):
        return False
    if not isinstance(items, list):
        return False
    if answers:
        return all(isinstance(item, dict) and "question" in item and "answer" in item for item in items)
    return all(isinstance(item, str) for item in items)


def _write_rules(db: sqlite3.Connection, table: str) -> None:
    """Install rules only on this tool connection. Existing SQLite files need no migration."""
    db.execute("PRAGMA recursive_triggers = ON")
    # REPLACE may implicitly delete an existing record. Require an explicit cleanup DELETE.
    db.execute(f"""CREATE TEMP TRIGGER protect_delete BEFORE DELETE ON {table}
        BEGIN SELECT RAISE(ABORT, 'Use a cleanup DELETE to remove a record'); END""")
    if table in CHECKPOINTS:
        stamp = CHECKPOINTS[table]
        for event in ("INSERT", "UPDATE"):
            db.execute(f"""CREATE TEMP TRIGGER valid_{event} BEFORE {event} ON {table}
                WHEN NEW.{stamp} IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.{stamp}, '+0 seconds')
                BEGIN SELECT RAISE(ABORT, 'Use a UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format'); END""")
        db.execute(f"""CREATE TEMP TRIGGER keep_checkpoint BEFORE UPDATE ON {table}
            WHEN OLD.{stamp} IS NOT NULL AND (NEW.{stamp} IS NULL OR NEW.{stamp} < OLD.{stamp})
            BEGIN SELECT RAISE(ABORT, 'A scan checkpoint cannot move backward'); END""")
        return

    db.create_function("valid_list", 2, _valid_list)
    for event in ("INSERT", "UPDATE"):
        db.execute(f"""CREATE TEMP TRIGGER check_{event} BEFORE {event} ON applications BEGIN
            SELECT CASE
              WHEN normalize_name(NEW.company_name) = '' OR trim(NEW.job_id) = ''
                THEN RAISE(ABORT, 'Provide a company name and a nonblank requisition ID')
              WHEN NEW.career_page_url IS NOT NULL AND NOT
                (NEW.career_page_url LIKE 'https://%' OR NEW.career_page_url LIKE 'http://%')
                THEN RAISE(ABORT, 'Provide an HTTP(S) careers URL')
              WHEN NEW.status = 'checked' AND (NEW.career_page_url IS NULL OR NEW.last_checked_at IS NULL)
                THEN RAISE(ABORT, 'A completed company scan needs its URL and timestamp')
              WHEN NEW.last_checked_at IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.last_checked_at, '+0 seconds')
                OR NEW.applied_at IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.applied_at, '+0 seconds')
                THEN RAISE(ABORT, 'Use UTC timestamps in YYYY-MM-DDTHH:MM:SSZ format')
              WHEN (NEW.questions_answers_json IS NOT NULL AND NOT valid_list(NEW.questions_answers_json, 1))
                OR NOT valid_list(NEW.status_notes_json, 0) THEN RAISE(ABORT, 'Invalid Q&A or status notes')
              WHEN NEW.status IN ('applied', 'failed_to_apply') AND
                (coalesce(normalize_name(NEW.job_name),'') = '' OR coalesce(trim(NEW.job_link),'') = ''
                 OR coalesce(trim(NEW.source_portal_url),'') = '' OR NEW.questions_answers_json IS NULL)
                THEN RAISE(ABORT, 'Save the job title, link, source and Q&A with the outcome')
              WHEN NEW.status != 'applied' AND NEW.applied_at IS NOT NULL
                THEN RAISE(ABORT, 'Only confirmed applications have a submission timestamp')
            END; END""")
        db.execute(f"""CREATE TEMP TRIGGER normalize_{event} AFTER {event} ON applications
            WHEN NEW.company_name IS NOT normalize_name(NEW.company_name)
              OR NEW.job_name IS NOT normalize_name(NEW.job_name)
              OR NEW.job_id IS NOT trim(NEW.job_id)
              OR (NEW.job_id IS NOT NULL AND NEW.application_id IS NULL)
              OR (NEW.status = 'applied' AND NEW.applied_at IS NULL)
            BEGIN UPDATE applications SET company_name = normalize_name(NEW.company_name),
                job_name = normalize_name(NEW.job_name), job_id = trim(NEW.job_id),
                application_id = CASE WHEN NEW.job_id IS NOT NULL THEN coalesce(NEW.application_id,
                    (SELECT coalesce(max(application_id), 0) + 1 FROM applications)) END,
                applied_at = CASE WHEN NEW.status = 'applied' THEN coalesce(NEW.applied_at,
                    strftime('%Y-%m-%dT%H:%M:%SZ','now')) END
                WHERE rowid = NEW.rowid;
                SELECT CASE WHEN EXISTS (SELECT 1 FROM applications WHERE rowid = NEW.rowid
                    AND (company_name IS NOT normalize_name(company_name)
                         OR job_name IS NOT normalize_name(job_name) OR job_id IS NOT trim(job_id)))
                    THEN RAISE(ABORT, 'Use normalize_name(?) for conflicting company names') END; END""")
    db.execute("""CREATE TEMP TRIGGER protect_history BEFORE UPDATE ON applications BEGIN
        SELECT CASE
          WHEN OLD.status = 'applied' AND (NEW.status != 'applied'
               OR normalize_name(NEW.company_name) IS NOT normalize_name(OLD.company_name)
               OR trim(NEW.job_id) IS NOT trim(OLD.job_id) OR
               (OLD.applied_at IS NOT NULL AND NEW.applied_at IS NOT OLD.applied_at))
            THEN RAISE(ABORT, 'Preserve the confirmed status and submission timestamp')
          WHEN OLD.job_id IS NULL AND NEW.career_page_url IS OLD.career_page_url
            AND OLD.last_checked_at IS NOT NULL AND
            (NEW.last_checked_at IS NULL OR NEW.last_checked_at < OLD.last_checked_at)
            THEN RAISE(ABORT, 'A scan checkpoint cannot move backward')
          WHEN NEW.job_id IS NULL AND NEW.career_page_url IS NOT OLD.career_page_url
            AND (NEW.status != 'not_checked' OR NEW.last_checked_at IS NOT NULL)
            THEN RAISE(ABORT, 'Reset status and last_checked_at when changing the careers URL')
        END; END""")


# SQL submitted to the tracker can use ordinary reporting functions and JSON values.
_SQL_FUNCTIONS = frozenset("""
    abs avg char coalesce concat count date datetime format glob group_concat hex ifnull iif
    instr julianday length like likelihood likely lower ltrim max min normalize_name nullif
    printf quote replace round rtrim sign strftime substr substring sum time total trim
    typeof unicode unixepoch unlikely upper valid_list
    json json_array json_array_length json_extract json_insert json_object json_patch json_quote
    json_remove json_replace json_set json_type json_valid json_group_array json_group_object -> ->>
    row_number rank dense_rank lag lead first_value last_value total_changes changes
""".split())


def table_sql(table: str, sql_query: str, parameters: list[SQLValue] | tuple = (), *,
              read_only: bool = False, cleanup: bool = False, database: Path = DATABASE) -> dict[str, Any]:
    """Execute one bound statement on one tracker table."""
    if table != "applications" and table not in CHECKPOINTS:
        raise ValueError("Unknown tracker table")
    if not isinstance(sql_query, str):
        raise ValueError("sql_query must be a string")
    match = re.match(r"\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\b", sql_query, re.IGNORECASE)
    if not match:
        raise ValueError("Use one SELECT, WITH ... SELECT, INSERT, UPDATE, or DELETE")
    verb = match[1].upper()
    reading = verb in ("SELECT", "WITH")
    if read_only and not reading:
        raise ValueError("The question agent can only read application history")
    if (verb == "DELETE") != cleanup:
        raise ValueError("Use cleanup=true only for an explicitly requested DELETE")

    def authorize(action, name, column, schema, source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and column in _SQL_FUNCTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and name in ("json_each", "json_tree"):
            return sqlite3.SQLITE_OK
        if name == table and schema in ("main", None):
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK
            if not reading and action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE) and not cleanup:
                return sqlite3.SQLITE_OK
            if cleanup and action == sqlite3.SQLITE_DELETE:
                return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    try:
        with (_read_history(database) if reading else _write(database)) as db:
            db.create_function("normalize_name", 1, lambda name: None if name is None else normalize_name(name),
                               deterministic=True)
            # Prepare SQLite's JSON table functions before restricting schema access.
            db.execute("SELECT 1 FROM json_each('[]'), json_tree('[]') LIMIT 0")
            if not reading and not cleanup:
                _write_rules(db, table)
            db.set_authorizer(authorize)
            try:
                cursor = db.execute(sql_query, parameters)
                columns = [field[0] for field in cursor.description or ()]
                rows = [{key: value.hex() if isinstance(value, bytes) else value
                         for key, value in zip(columns, row)} for row in cursor]
                result: dict[str, Any] = {"columns": columns, "rows": rows}
                if not reading:
                    result["affected"] = cursor.rowcount
                return result
            finally:
                db.set_authorizer(None)
    except sqlite3.Error as error:
        raise ValueError(f"{table}: {error}") from error


def read_applications(sql_query: str, parameters: list[SQLValue] | tuple = ()) -> dict[str, Any]:
    """Read history for the question agent and the CLI."""
    return table_sql("applications", sql_query, parameters, read_only=True)


def record_job_outcome(company_name: str, job_id: str, job_name: str, job_link: str, source_portal_url: str,
                       status: JobStatus, questions_answers: Sequence[Mapping[str, object]],
                       notes: list[str] | None = None, *, database: Path = DATABASE) -> dict:
    """Save a claimed opening's outcome. Only an identical terminal outcome can be replayed."""
    if not job_name.strip():
        raise ValueError("Provide the job title")
    urls = [job_link] if source_portal_url == "WhatsApp" else [job_link, source_portal_url]
    for link in urls:
        url = urlsplit(link)
        if url.scheme not in ("http", "https") or not url.hostname or any(c.isspace() for c in link):
            raise ValueError("Provide the posting URL and the discovery URL or WhatsApp")
    if notes and (len(notes) > 5 or any(not note.strip() or "\n" in note or "\r" in note for note in notes)):
        raise ValueError("Use up to five single-line status notes")

    result = table_sql("applications", """
        UPDATE applications SET job_name = ?1, job_link = ?2, source_portal_url = ?3, status = ?4,
            questions_answers_json = ?5, status_notes_json = coalesce(?6, status_notes_json)
        WHERE company_name = normalize_name(?7) AND job_id = ?8
          AND (status = 'in_progress' OR (status = ?4 AND job_name = normalize_name(?1)
               AND job_link = ?2 AND source_portal_url = ?3 AND questions_answers_json = ?5
               AND status_notes_json = coalesce(?6, status_notes_json)))
    """, (job_name, job_link, source_portal_url, status, json.dumps(questions_answers, sort_keys=True),
          json.dumps(notes) if notes is not None else None, company_name, job_id.strip()), database=database)
    if result["affected"] != 1:
        raise ValueError("No active claim or identical recorded outcome for this employer and requisition")
    return {"status": status, "affected": result["affected"]}


if __name__ == "__main__":
    print(initialize())
