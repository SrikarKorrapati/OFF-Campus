"""Tool schemas for the question graph and application workers."""

TOOL_DEFINITIONS = [
    {
        "name": "query_the_schema",
        "description": (
            "Run one read-only SQLite query and return the columns and rows. "
            "job_portals(id, name, last_accessed_at) lists discovery portals and their last "
            "successful scan starts in UTC. A NULL timestamp means the portal has never been scanned. "
            "whatsapp_channels(channel_id, last_checked_at) stores the UTC start of each channel's last completed scan. "
            "CREATE TABLE applications (company_name TEXT, career_page_url TEXT, last_checked_at TEXT, "
            "application_id INTEGER, job_id TEXT, job_name TEXT, job_link TEXT, source_portal_url TEXT, "
            "applied_at TEXT, questions_answers_json TEXT, status TEXT, status_notes_json TEXT). "
            "Company rows have NULL job_id and status 'not_checked' or 'checked'. "
            "Job attempts are keyed by company_name and job_id. A claimed opening is 'in_progress'. "
            "Count confirmed submissions with "
            "status = 'applied'. A failed attempt is 'failed_to_apply'. Names are uppercase with "
            "underscores. Timestamps are ISO 8601 UTC. career_page_url is the employer's portal, "
            "job_link is the opening, and source_portal_url is where it was found. "
            "The JSON lists hold question/answer objects and status notes, respectively."
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

# Application workers claim openings. The question graph only needs history.
WORKER_TOOL_DEFINITIONS = [*TOOL_DEFINITIONS, {
    "name": "claim_job",
    "description": (
        "Call once per opening before starting its application. Returns claimed=true only to the worker "
        "that acquired it. If false, skip the opening: status is in_progress or applied. "
        "Previously failed openings may be claimed again. Use query_the_schema for later status checks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "company_name": {"type": "string", "description": "Employer name as listed on the opening."},
            "job_id": {"type": "string", "description": "The employer's requisition ID for this opening."},
        },
        "required": ["company_name", "job_id"],
        "additionalProperties": False,
    },
}]
