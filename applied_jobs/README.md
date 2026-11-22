# Company shortlist and application tracker

## Shortlist employers

Keep the shortlist in `applied_jobs/company_seed.csv` on your machine. Git ignores seed CSVs. Add each employer once. Select private-sector teams that build their own products, infrastructure, or technology. Exclude services-led consultancies, outsourced engineering or staffing companies, and government or public-sector undertakings.

| Employer | Evidence to record |
| --- | --- |
| All | Record an India-based software, AI, embedded, forward-deployed, or related hands-on engineering role in `engineering_role` and its source in `role_source`. |
| Non-YC | Reported India graduate or entry-level technical compensation above ₹15 LPA total CTC in `reported_ctc_lpa`, with a plain-text reference in `salary_source`. |
| YC-backed | The YC profile, Indian office location, and source for that location. YC employers qualify without a company-level pay cutoff. |

After each verified batch, run `python3 applied_jobs/seed_company_portals.py` from the project root. Rerunning preserves submissions and check times for unchanged careers URLs. Verify eligibility and pay for each opening before applying.

## Application records

The SQLite `applications` table stores two kinds of rows. Both timestamps use ISO 8601 UTC.

| Row | Contents |
| --- | --- |
| Company | Start with the normalized `company_name`, the known `career_page_url`, and status `not_checked`. Checking the portal sets `last_checked_at` and status `checked`. |
| Job attempt | `company_name` and `job_id` identify the opening. Keep the job title, listing URL, discovery URL, questions, and answers. A confirmed submission gets status `applied` and a submission time in `applied_at`. A failed attempt gets `failed_to_apply` and no submission time. |

Use `query_the_schema(sql_query)` for history. Filter by `status = 'applied'` to count submissions. `save_application` defaults to `applied`. For a failed attempt, pass `status="failed_to_apply"` and a reason such as `status_notes=["Portal closed before submission."]`. The `status_notes_json` column holds up to five concise, single-line bullets. Notes are optional for a confirmed submission and can include a confirmation reference or next step.

The first write to a legacy database saves a full backup, including legacy portal names, alongside it as `applications.sqlite3.pre-migration-*.sqlite3`.

## Question workflow

Run these commands from the project root with Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Keep identity, education, experience, skills, and project details in `docs/candidate_profile.md`. Keep availability and compensation preferences in `docs/job_requirements.md`. Pass a configured chat model to `build_question_graph` in [question_graph.py](../question_graph.py).

To migrate a split profile, move the contents of `personal_details.md` and `technical_details.md` into the candidate profile under `## Personal Details` and `## Technical Details`. The loader uses each old file until its corresponding heading is present.
