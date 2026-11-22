# Company shortlist and application tracker

Employer shortlist criteria and registration instructions are in `docs/application_workflow.md`.

If you have an older checkout, stop any tracker processes and move your local files from `applied_jobs/` into `job_tracker/` before running the tracker. Keep the SQLite database with its sidecar files, move `whatsapp_scan/` if present, and rename `company_seed.csv` to `company_shortlist.csv`.

On upgrade, the tracker imports any existing `whatsapp_scan/last_checked.json` entries into `whatsapp_channels(channel_id, last_checked_at)`. Future channel scans use this table.

## Application records

The SQLite `applications` table stores two kinds of rows. Both timestamps use ISO 8601 UTC.

| Row | Contents |
| --- | --- |
| Company | Start with the normalized `company_name`, the known `career_page_url`, and status `not_checked`. Completing a full careers-page scan sets `last_checked_at` and status `checked`. |
| Job attempt | `company_name` and `job_id` identify the opening. Keep the job title, listing URL, discovery source (the employer’s careers URL, a job-board URL or `WhatsApp`), questions, and answers. A confirmed submission gets status `applied` and a submission time in `applied_at`. A failed attempt gets `failed_to_apply` and no submission time. |

Use `query_the_schema(sql_query)` for history. Filter by `status = 'applied'` to count submissions. `save_application` defaults to `applied`. For a failed attempt, pass `status="failed_to_apply"` and a reason such as `status_notes=["Portal closed before submission."]`. The `status_notes_json` column holds up to five concise, single-line bullets. Notes are optional for a confirmed submission and can include a confirmation reference or next step.

Application workers use `WORKER_TOOL_DEFINITIONS` from [tool_definitions.py](tool_definitions.py) and `WORKER_TOOL_HANDLERS` from [database.py](database.py). Call `claim_job(company_name, job_id)` before opening the application tab. Only the worker that receives `claimed: true` proceeds. Later calls return `claimed: false` for an opening that is `in_progress` or `applied`. A `failed_to_apply` opening can be claimed again. Use `query_the_schema` for status checks.

## Question workflow

Run these commands from the project root with Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Keep identity, education, experience, skills, and project details in `docs/candidate_profile.md`. Keep availability and compensation preferences in `docs/job_requirements.md`. Pass a configured chat model to `build_question_graph` in [application_questions.py](../application_questions.py).

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
