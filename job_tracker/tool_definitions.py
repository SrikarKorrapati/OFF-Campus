"""Tool definitions for the tracker MCP server and the application question graph."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from typing_extensions import NotRequired, TypedDict

from . import database


class PortalField(TypedDict):
    question: str
    allowed_options: NotRequired[list[str]]
    allow_multiple: NotRequired[bool]
    max_length: NotRequired[int]


class PageAnswers(TypedDict):
    answers: dict[str, str]
    needs_input: dict[str, str]


class RecordedAnswer(TypedDict):
    question: str
    answer: str


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


def _register_sql_tool(server: FastMCP, table: str) -> None:
    @server.tool(name=f"{table}_sql", description=(
        f"Query or edit only {table}. " + TABLES[table] +
        " Send one SELECT, WITH ... SELECT, INSERT, UPDATE, or DELETE. Bind values to ? with "
        "parameters. Results contain columns and rows, plus affected for writes. Set cleanup=true "
        "only for a DELETE explicitly requested by the user."
    ), annotations=ToolAnnotations(openWorldHint=False, destructiveHint=True))
    def run_sql(sql_query: str, parameters: list[database.SQLValue] | None = None,
                cleanup: bool = False) -> dict:
        return database.table_sql(table, sql_query, parameters or [], cleanup=cleanup)


def register_mcp_tools(server: FastMCP) -> None:
    for table in TABLES:
        _register_sql_tool(server, table)

    @server.tool(annotations=ToolAnnotations(openWorldHint=False, destructiveHint=False))
    def claim_job(company_name: str, job_id: str) -> dict:
        """Register the verified employer and reserve its requisition. Only the worker receiving claimed=true proceeds."""
        return database.claim_job(company_name, job_id)

    @server.tool(annotations=ToolAnnotations(openWorldHint=False, destructiveHint=False, idempotentHint=True))
    def record_job_outcome(company_name: str, job_id: str, job_name: str, job_link: str, source_portal_url: str,
                           status: database.JobStatus, questions_answers: list[RecordedAnswer],
                           notes: list[str] | None = None) -> dict:
        """Save one claimed job's actual answers and outcome. Use in_progress for an uncertain submission.

        Pass the verified posting URL and the discovery URL or WhatsApp. Notes accept up to five short lines.
        """
        return database.record_job_outcome(company_name, job_id, job_name, job_link, source_portal_url,
                                           status, questions_answers, notes)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def answer_application_fields(company: str, job_id: str, job_description: str,
                                        fields: dict[str, PortalField], resume_text: str = "") -> PageAnswers:
        """Draft and review a page's independent fields keyed by stable ID. Returns answers and needs_input by ID."""
        from application_questions import answer_page

        return await answer_page({"company": company, "job_id": job_id, "job_description": job_description,
                                  "fields": fields, "resume_text": resume_text})
