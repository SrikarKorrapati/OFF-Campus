# Company shortlist and application tracker

Employer shortlist criteria and registration instructions are in `docs/general_instructions.md`.

## Application records

The SQLite `applications` table stores two kinds of rows. Both timestamps use ISO 8601 UTC.

| Row | Contents |
| --- | --- |
| Company | Start with the normalized `company_name`, the known `career_page_url`, and status `not_checked`. Checking the portal sets `last_checked_at` and status `checked`. |
| Job attempt | `company_name` and `job_id` identify the opening. Keep the job title, listing URL, discovery URL, questions, and answers. A confirmed submission gets status `applied` and a submission time in `applied_at`. A failed attempt gets `failed_to_apply` and no submission time. |

Use `query_the_schema(sql_query)` for history. Filter by `status = 'applied'` to count submissions. `save_application` defaults to `applied`. For a failed attempt, pass `status="failed_to_apply"` and a reason such as `status_notes=["Portal closed before submission."]`. The `status_notes_json` column holds up to five concise, single-line bullets. Notes are optional for a confirmed submission and can include a confirmation reference or next step.

The tracker creates the table on first write and uses schema version 4.

## Question workflow

Run these commands from the project root with Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Keep identity, education, experience, skills, and project details in `docs/candidate_profile.md`. Keep availability and compensation preferences in `docs/job_requirements.md`. Pass a configured chat model to `build_question_graph` in [question_graph.py](../question_graph.py).

To migrate a split profile, move the contents of `personal_details.md` and `technical_details.md` into the candidate profile under `## Personal Details` and `## Technical Details`. The loader uses each old file until its corresponding heading is present.
