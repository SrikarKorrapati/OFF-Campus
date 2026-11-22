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

## Tracker tools

When a chat's tool list omits the tracker, run these commands from the project root. The first lists the live MCP tools and their arguments. The second calls one through the same server.

```sh
.venv/bin/python -m job_tracker.cli mcp
echo '{"sql_query":"SELECT count(*) AS tracked_rows FROM applications"}' | .venv/bin/python -m job_tracker.cli mcp applications_sql
```

Each SQL tool accepts one statement, an optional list of parameters for `?` placeholders, and returns `columns` and `rows`. Writes also return `affected`. Use SELECT (including WITH ... SELECT), INSERT, UPDATE or DELETE on the tool’s table. For an explicitly requested deletion, pass `cleanup=true` and identify the records in the WHERE clause. Routine scans leave cleanup off. Read back a row after a write to see normalized names, generated IDs and timestamps.

| Tool | Use |
| --- | --- |
| `applications_sql` | Look up employers and applications, register careers pages, and update outcomes. The question writer receives a read-only version of this tool. |
| `job_portals_sql` | Read the discovery sources and update each completed scan’s UTC start time. |
| `whatsapp_channels_sql` | Read and update each followed channel’s checkpoint. |
| `claim_job(company_name, job_id)` | Atomically reserve a new or previously failed opening. Proceed only when `claimed` is true. |
| `record_job_outcome` | Save the job details, Q&A and outcome for a claimed opening. |
| `answer_application_fields` | Draft and review a page of questions. Returns approved answers and missing facts by field ID. |

The [daily scan](daily_scan.py) uses the [source functions](scan_sources.py) to select work and update checkpoints. The [project configuration](../.codex/config.toml) launches the server, which creates or upgrades the tracker on startup. To start it from another stdio client, run `.venv/bin/python -m job_tracker.mcp_server` in the project root.

## Local application history

The CLI keeps three read-only shortcuts. Run `.venv/bin/python -m job_tracker.cli` followed by one of the commands below.

| Command | Result |
| --- | --- |
| `recent 24` | Distinct employers with confirmed submissions in the last 24 hours, most recent first. |
| `applied "Sarvam AI"` | Whether any submission to the employer was confirmed. |
| `status "Sarvam AI"` | The employer’s careers-page status and recorded applications. |

## Question workflow

Run these commands from the project root with Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Keep identity, education, experience, skills, and project details in the [candidate profile](../docs/candidate_profile.md). Keep availability and compensation preferences in [job requirements](../docs/job_requirements.md). The question tool reads `OPENAI_API_KEY` from the environment or the project’s local `.env`. Set `OPENAI_MODEL` to override its default `gpt-4.1-mini`. Python callers can also pass a configured model to `build_question_graph` in [application_questions.py](../application_questions.py).

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
