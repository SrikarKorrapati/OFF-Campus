# Company shortlist and application tracker

## Shortlist employers

Add each employer once to the [shortlist CSV](company_seed.csv). Select private-sector teams that build their own products, infrastructure, or technology. Exclude services-led consultancies, outsourced engineering or staffing companies, and government or public-sector undertakings.

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
| Company | Start with the normalized `company_name` and the employer's `career_page_url` when known. All other fields start as NULL. A portal check sets `last_checked_at`. |
| Submission | `company_name` and `job_id` together identify the opening. Store the job title, listing URL, `source_portal_url` where it was found, `applied_at`, and application questions and answers. |

Use `query_the_schema(sql_query)` for read-only history lookups and `save_application` to record a confirmed submission. The first write to a legacy database saves a full backup, including legacy portal names, alongside it as `applications.sqlite3.pre-migration-*.sqlite3`.

## Question workflow

Keep identity, education, experience, skills, and project details in `docs/candidate_profile.md`. Keep availability and compensation preferences in `docs/job_requirements.md`. Pass a configured chat model to `build_question_graph` in [question_graph.py](../question_graph.py).

To migrate a split profile, move the contents of `personal_details.md` and `technical_details.md` into the candidate profile under `## Personal Details` and `## Technical Details`. The loader uses each old file until its corresponding heading is present.
