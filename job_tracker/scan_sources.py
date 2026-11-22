"""Select sources and save their completed scan boundaries in the local tracker."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .database import DATABASE, SAVE_CHANNEL_CHECKPOINT, _write, normalize_name, table_sql

PORTAL_URLS = {
    "Y Combinator": "https://www.ycombinator.com/jobs/role/all/india",
    "Wellfound": "https://wellfound.com/location/india",
    "Cutshort": "https://cutshort.io/jobs",
    "Hirist": "https://www.hirist.tech/",
    "DevsUnite": "https://devsunite.com/jobs",
    "Internshala": "https://internshala.com/jobs/",
    "Freshersworld": "https://www.freshersworld.com/freshers",
    "LinkedIn": "https://in.linkedin.com/jobs/fresher-entry-level-jobs",
    "Naukri": "https://www.naukri.com/fresher-jobs-in-india",
    "Indeed": "https://in.indeed.com/Fresher-jobs-in-India",
    "Foundit": "https://www.foundit.in/search/fresher-jobs-in-india",
    "Shine": "https://www.shine.com/job-search/fresher-jobs",
    "WhatsApp": "https://web.whatsapp.com/",
}

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(UTC_FORMAT)


def _parse_start(scan_start: str) -> datetime:
    started = datetime.strptime(scan_start, UTC_FORMAT).replace(tzinfo=timezone.utc)
    if started.strftime(UTC_FORMAT) != scan_start:
        raise ValueError("Use a UTC scan_start in YYYY-MM-DDTHH:MM:SSZ format")
    return started


def due_companies(scan_start: str, *, database: Path = DATABASE) -> list[dict]:
    """Select the shortlist once per run. Each selected employer needs all active jobs checked."""
    due_by = _parse_start(scan_start) - timedelta(hours=72)
    return table_sql("applications", """
        SELECT company_name, career_page_url, last_checked_at FROM applications
        WHERE job_id IS NULL AND (last_checked_at IS NULL OR last_checked_at <= ?)
        ORDER BY last_checked_at, company_name
    """, (due_by.strftime(UTC_FORMAT),), database=database)["rows"]


def first_cutoff(scan_start: str) -> str:
    """A new board or channel starts two weeks before this scan."""
    return (_parse_start(scan_start) - timedelta(days=14)).strftime(UTC_FORMAT)


def list_portals(scan_start: str, *, database: Path = DATABASE) -> list[dict]:
    """Return every configured portal, its starting URL and its inclusive posting cutoff."""
    rows = table_sql("job_portals", """
        SELECT id, name, coalesce(last_accessed_at, ?) AS cutoff FROM job_portals ORDER BY id
    """, (first_cutoff(scan_start),), database=database)["rows"]
    return [{**row, "url": PORTAL_URLS.get(row["name"])} for row in rows]


def channel_checkpoints(*, database: Path = DATABASE) -> dict[str, str]:
    """Read the saved times for a worker discovering followed channels live."""
    rows = table_sql("whatsapp_channels", """
        SELECT channel_id, last_checked_at FROM whatsapp_channels
    """, database=database)["rows"]
    return {row["channel_id"]: row["last_checked_at"] for row in rows}


def complete_company(company_name: str, previous_url: str | None, verified_url: str,
                     scan_start: str, *, database: Path = DATABASE) -> None:
    """Complete the selected company's verified page, atomically registering a URL correction."""
    _parse_start(scan_start)
    url = urlsplit(verified_url)
    if url.scheme not in ("https", "http") or not url.hostname:
        raise ValueError("A completed company scan needs a verified HTTP(S) careers URL")
    name = normalize_name(company_name)
    with _write(database) as connection:
        row = connection.execute("""
            SELECT career_page_url, last_checked_at FROM applications
            WHERE company_name = ? AND job_id IS NULL
        """, (name,)).fetchone()
        if row is None:
            raise ValueError(f"No shortlisted company named {name}")
        current_url, last_checked_at = row
        if current_url != verified_url:
            if current_url != previous_url or (last_checked_at and last_checked_at > scan_start):
                raise ValueError(f"Careers page for {name} changed during the scan")
            connection.execute("""
                UPDATE applications SET career_page_url = ?, status = 'not_checked',
                    last_checked_at = NULL, status_notes_json = '[]'
                WHERE company_name = ? AND job_id IS NULL
            """, (verified_url, name))
        connection.execute("""
            UPDATE applications SET status = 'checked', last_checked_at = max(coalesce(last_checked_at, ''), ?)
            WHERE company_name = ? AND job_id IS NULL
        """, (scan_start, name))


def complete_portal(portal_id: int, scan_start: str, *, database: Path = DATABASE) -> None:
    """Save the completed scan start, preserving a newer overlapping run's checkpoint."""
    _parse_start(scan_start)
    result = table_sql("job_portals", """
        UPDATE job_portals SET last_accessed_at = max(coalesce(last_accessed_at, ''), ?) WHERE id = ?
    """, (scan_start, portal_id), database=database)
    if result["affected"] != 1:
        raise ValueError(f"Unknown portal ID {portal_id}")


def complete_channel(channel_id: str, scan_start: str, *, database: Path = DATABASE) -> None:
    """Save one successfully covered WhatsApp channel's start, including an empty scan."""
    _parse_start(scan_start)
    if not channel_id.strip():
        raise ValueError("Provide the stable WhatsApp channel ID")
    table_sql("whatsapp_channels", SAVE_CHANNEL_CHECKPOINT, (channel_id, scan_start), database=database)
