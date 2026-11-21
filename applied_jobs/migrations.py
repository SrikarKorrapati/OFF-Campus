"""Initialize the tracker and keep earlier SQLite layouts readable."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile


SCHEMA_VERSION = 3


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _read_only(database):
    return sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)


def _backup(database):
    with NamedTemporaryFile(dir=database.parent, prefix=f"{database.name}.pre-migration-",
                            suffix=".sqlite3", delete=False) as file:
        path = Path(file.name)
    try:
        with closing(_read_only(database)) as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _backfill_statuses(connection, columns):
    checked = "WHEN NULLIF(last_checked_at, '') IS NOT NULL THEN 'checked'" if "last_checked_at" in columns else ""
    connection.execute(f"""
        UPDATE applications SET status = CASE
            WHEN job_id IS NOT NULL THEN 'applied' {checked} ELSE 'not_checked'
        END
    """)


def _add_status_columns(connection, columns):
    # ALTER preserves v2 rowids and indexes, including indexes added by the user.
    connection.execute("""
        ALTER TABLE applications ADD COLUMN status TEXT NOT NULL DEFAULT 'not_checked'
        CHECK (status IN ('not_checked', 'checked', 'applied', 'failed_to_apply'))
    """)
    _backfill_statuses(connection, columns)

    # SQLite CHECKs cannot use json_each(). Validate each of the five possible notes.
    notes = [f"json_extract(status_notes_json, '$[{i}]')" for i in range(5)]
    valid_notes = " AND ".join(
        f"coalesce(json_type(status_notes_json, '$[{i}]') = 'text' "
        f"AND trim({note}, char(9, 32)) <> '', 1)" for i, note in enumerate(notes)
    )
    connection.execute(f"""
        ALTER TABLE applications ADD COLUMN status_notes_json TEXT NOT NULL DEFAULT '[]'
        CHECK (CASE WHEN json_valid(status_notes_json) THEN
            (job_id IS NULL) = (status IN ('not_checked', 'checked'))
            AND json_type(status_notes_json) = 'array'
            AND json_array_length(status_notes_json) BETWEEN (status = 'failed_to_apply') AND 5
            AND {valid_notes}
            AND printf('%s%s%s%s%s', {', '.join(notes)})
                NOT GLOB ('*[' || char(10, 11, 12, 13, 28, 29, 30, 133, 8232, 8233) || ']*')
        ELSE 0 END)
    """)


@contextmanager
def read_history(database: Path, schema_path: Path):
    """Read current or legacy history without creating a database or a backup on disk."""
    if not database.is_file() or not database.stat().st_size:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            connection.execute("PRAGMA query_only = ON")
            yield connection
        return

    with closing(_read_only(database)) as source:
        source.execute("PRAGMA query_only = ON")
        source.execute("BEGIN")
        columns = _columns(source, "applications")
        if "status" in columns or "job_id" not in columns:
            yield source
            return
        # Preserve legacy columns (including portal_name) for callers querying old history.
        with closing(sqlite3.connect(":memory:")) as snapshot:
            source.backup(snapshot)
            source.rollback()
            _add_status_columns(snapshot, columns)
            for name in ("source_portal_url", "applied_at"):
                if name not in columns:
                    snapshot.execute(f"ALTER TABLE applications ADD COLUMN {name} TEXT")
            snapshot.execute("PRAGMA query_only = ON")
            yield snapshot


def _copy_legacy_jobs(connection, columns):
    fields = {"application_id": "COALESCE(application_id, rowid)" if "application_id" in columns else "rowid"}
    for name in ("company_name", "job_id", "job_name", "job_link", "source_portal_url",
                 "applied_at", "questions_answers_json", "career_page_url", "last_checked_at"):
        if name in columns:
            fields[name] = f"NULLIF({name}, '')" if name in ("career_page_url", "last_checked_at") else name
    connection.execute(f"""
        INSERT INTO applications (rowid, {', '.join(fields)}, status)
        SELECT rowid, {', '.join(fields.values())}, 'applied'
        FROM previous_applications WHERE job_id IS NOT NULL
    """)


def _copy_legacy_portals(connection, table, columns):
    fields = ["company_name"] + [name for name in ("career_page_url", "last_checked_at") if name in columns]
    values = ["company_name"] + [f"NULLIF({name}, '')" for name in fields[1:]]
    where = "WHERE job_id IS NULL" if "job_id" in columns else ""
    connection.execute(f"""
        INSERT INTO applications ({', '.join(fields)})
        SELECT {', '.join(values)} FROM {table} {where}
    """)
    connection.execute(f"DROP TABLE {table}")


def initialize(database: Path, schema_path: Path) -> Path:
    """Install the current schema or atomically upgrade a legacy tracker after backing it up."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return database
        if version > SCHEMA_VERSION:
            raise ValueError("This database uses a newer application schema")

        jobs = _columns(connection, "applications")
        portals = _columns(connection, "company_portal_checks")
        if jobs or portals:
            _backup(database)
        if version == 2:
            _add_status_columns(connection, jobs)
        else:
            if jobs:
                connection.execute("ALTER TABLE applications RENAME TO previous_applications")
                connection.execute("DROP INDEX IF EXISTS applications_company_portal_unique")
            # executescript commits any open transaction before running its SQL.
            for statement in schema_path.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    connection.execute(statement)
            if "job_id" in jobs:
                _copy_legacy_jobs(connection, jobs)
            if jobs:
                _copy_legacy_portals(connection, "previous_applications", jobs)
            if portals:
                _copy_legacy_portals(connection, "company_portal_checks", portals)
            if jobs or portals:
                _backfill_statuses(connection, {"last_checked_at"})
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return database
