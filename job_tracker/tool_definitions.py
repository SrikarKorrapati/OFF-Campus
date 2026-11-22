"""Descriptions shared by the tracker MCP server and the application question graph."""

TABLES = {
    "applications": (
        "applications(company_name, career_page_url, last_checked_at, application_id, job_id, "
        "job_name, job_link, source_portal_url, applied_at, questions_answers_json, status, "
        "status_notes_json). A NULL job_id identifies an employer. For jobs, use company_name "
        "and the employer's job_id. Status is not_checked/checked for employers or "
        "in_progress/applied/failed_to_apply for jobs. SQLite normalizes company and job names "
        "on write. Use normalize_name(?) for lookups or upsert keys. Save Q&A as a JSON array "
        "of question/answer objects and notes as a JSON array of strings."
    ),
    "job_portals": (
        "job_portals(id, name, last_accessed_at). One row per discovery portal. A NULL timestamp "
        "means never checked. Save a completed scan's UTC start in YYYY-MM-DDTHH:MM:SSZ format."
    ),
    "whatsapp_channels": (
        "whatsapp_channels(channel_id, last_checked_at). One row per followed channel, keyed by "
        "its stable ID. Save the UTC start of its latest completed scan in YYYY-MM-DDTHH:MM:SSZ format."
    ),
}

# The answer writer has one read-only tool. Application workers use the MCP server.
TOOL_DEFINITIONS = [{
    "name": "applications_sql",
    "description": "Read application history with one SELECT or WITH ... SELECT. " + TABLES["applications"],
    "parameters": {
        "type": "object",
        "properties": {
            "sql_query": {"type": "string", "description": "One read-only SQL query."},
            "parameters": {
                "type": "array", "description": "Values for ? placeholders, or an empty list.",
                "items": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}]},
            },
        },
        "required": ["sql_query", "parameters"],
        "additionalProperties": False,
    },
}]
