"""Read application history from the local tracker."""

from math import isfinite
from typing import Any

from .database import normalize_name, query_the_schema


def _company_name(value: str) -> str:
    name = normalize_name(value)
    if not name:
        raise ValueError("Enter a company name.")
    return name


def list_recently_applied_companies(hours: float) -> list[str]:
    """List distinct companies with confirmed submissions in the past X hours, most recent first.

    Use a positive number of hours (e.g. 24 for the last day). An empty list means no matches.
    """
    if not isfinite(hours) or hours <= 0:
        raise ValueError("Hours must be a positive, finite number.")
    result = query_the_schema("""
        SELECT company_name FROM applications
        WHERE job_id IS NOT NULL AND status = 'applied'
          AND (strftime('%s', 'now') - strftime('%s', applied_at)) BETWEEN 0 AND ? * 3600
        GROUP BY company_name
        ORDER BY MAX(applied_at) DESC, company_name
    """, parameters=(hours,))
    return [row["company_name"] for row in result["rows"]]


def has_applied_to_company(company_name: str) -> bool:
    """Return true if the tracker contains a confirmed submission to this company at any time.

    A shortlist entry, an in-progress form or a failed attempt alone returns false.
    """
    result = query_the_schema("""
        SELECT 1 FROM applications
        WHERE company_name = ? AND job_id IS NOT NULL AND status = 'applied' LIMIT 1
    """, parameters=(_company_name(company_name),))
    return bool(result["rows"])


def get_company_status(company_name: str) -> dict[str, Any]:
    """Get the company's careers-page scan and each job's recorded application status.

    Returns found, portal (URL, status, last check), and applications (ID, title, link,
    status, submission time). An unknown company returns found=false and an empty job list.
    """
    name = _company_name(company_name)
    rows = query_the_schema("""
        SELECT career_page_url, last_checked_at, job_id, job_name, job_link, status, applied_at
        FROM applications WHERE company_name = ?
        ORDER BY applied_at DESC, job_id
    """, parameters=(name,))["rows"]
    portal = None
    applications = []
    job_fields = ("job_id", "job_name", "job_link", "status", "applied_at")
    for row in rows:
        if row["job_id"] is None:
            portal = {key: row[key] for key in ("career_page_url", "status", "last_checked_at")}
        else:
            applications.append({key: row[key] for key in job_fields})
    return {"company_name": name, "found": bool(rows), "portal": portal, "applications": applications}
