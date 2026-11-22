# Company shortlist and application tracker

Select employers using the [job requirements](../docs/job_requirements.md).

If you have an older checkout, stop any tracker processes and move your local files from `applied_jobs/` into `job_tracker/` before running the tracker. Keep the SQLite database with its sidecar files, move `whatsapp_scan/` if present, and rename `company_seed.csv` to `company_shortlist.csv`.

On upgrade, the tracker imports any existing `whatsapp_scan/last_checked.json` entries into `whatsapp_channels(channel_id, last_checked_at)`. Future channel scans use this table.

## Application records

The SQLite `applications` table stores two kinds of rows. Both timestamps use ISO 8601 UTC.

| Row | Contents |
| --- | --- |
| Company | Start with the normalized `company_name`, the known `career_page_url`, and status `not_checked`. Completing a full careers-page scan sets `last_checked_at` and status `checked`. |
| Job attempt | `company_name` and `job_id` identify the opening. Keep the job title, listing URL, discovery source (the employer’s careers URL, a job-board URL or `WhatsApp`), questions, and answers. A confirmed submission gets status `applied` and a submission time in `applied_at`. A failed attempt gets `failed_to_apply` and no submission time. |

## Local application history

The MCP server and CLI call the same three read-only [history functions](history.py) against the local SQLite tracker. The daily application workflow calls its own internal Python functions directly.

| MCP tool | CLI example | Result |
| --- | --- | --- |
| `list_recently_applied_companies(hours)` | `recent 24` | Distinct employers with confirmed submissions in the requested time window, most recent first. |
| `has_applied_to_company(company_name)` | `applied "Sarvam AI"` | True if any submission to that employer was confirmed. |
| `get_company_status(company_name)` | `status "Sarvam AI"` | Whether the employer is known, its careers-page scan status if tracked, and the status and details of each recorded job attempt. |

Run the CLI from the project root, for example `.venv/bin/python -m job_tracker.cli recent 24`. It prints JSON. To connect a local MCP client, have it launch `.venv/bin/python -m job_tracker.mcp_server` from the same directory over stdio. [Codex client configuration](../.codex/config.toml)

## Question workflow

Run these commands from the project root with Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Keep identity, education, experience, skills, and project details in the [candidate profile](../docs/candidate_profile.md). Keep availability and compensation preferences in [job requirements](../docs/job_requirements.md). The question graph reads `OPENAI_API_KEY` from the environment or the project’s local `.env`. Set `OPENAI_MODEL` to override its default `gpt-4.1-mini`. Python callers can also pass a configured model to `build_question_graph` in [application_questions.py](../application_questions.py).

Build the graph once per application and invoke it with fresh fields for each page or conditional section. Use a stable control name or a section-and-label key for each ID so it still identifies the field after the page changes.

```python
from application_questions import build_question_graph

graph = build_question_graph(model)
context = {"company": company, "job_id": job_id, "job_description": description, "resume_text": resume}
result = graph.invoke({**context, "fields": {
    "role_type": {"question": "Which role?", "allowed_options": ["Internship", "Full-time"]},
    "motivation": {"question": "Why this role?", "max_length": 350},
}})
```

`result["answers"]` contains approved strings keyed by field ID. `result["needs_input"]` gives a reason for each unresolved field. The writer and critic handle a batch together and retry only rejected fields, up to three drafts each. A multiple-choice field accepts one label by default. Set `allow_multiple=True` for a multi-select, whose answer contains one displayed label per line.

A browser worker can call `fill_question_page(graph, context, read_fields=read_fields, fill_field=fill_field)` for each page. Its reader returns a fresh mapping of visible, unanswered fields. Its fill action resolves the current control by ID, enters the approved answer, and verifies that the portal accepted it. The loop reads the form again after each choice and batches new or changed questions. The worker controls navigation and submission.

To migrate a split profile, move the contents of `personal_details.md` and `technical_details.md` into the candidate profile under `## Personal Details` and `## Technical Details`. The loader uses each old file until its corresponding heading is present.
