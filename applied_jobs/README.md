# Company shortlist and application history

From the project root, run `python3 applied_jobs/seed_company_portals.py` to load [the shortlist](company_seed.csv). Running it again preserves submitted applications and the last check time for unchanged careers URLs.

The SQLite database has one table, `applications`.

| Row | Values |
| --- | --- |
| New company | `company_name` and, when known, `career_page_url`. Every other column starts as SQL NULL. |
| Checked company | `last_checked_at` records when its careers page was checked. |
| Submitted application | The employer and its `job_id` identify the application. The row holds the job title, listing URL, discovery portal URL, submission time and answers. |

`career_page_url` points to the employer's careers page or its hiring board. `source_portal_url` records where a particular opening was discovered. Both timestamps use ISO 8601 UTC text, such as `2026-11-21T14:30:00Z`.

The agent uses one read-only SQLite tool, `query_the_schema(sql_query)`, for application dates, job IDs, and duplicate checks. Before submitting, query by both `company_name` and `job_id` because employers can reuse requisition IDs. The submission workflow calls `save_application` after the portal confirms success.

To run the question workflow, place your own `personal_details.md`, `candidate_profile.md`, `technical_details.md`, and `job_requirements.md` in `docs/` and pass a configured chat model to `build_question_graph` in `question_graph.py`.

On the first write to an older layout, the tracker saves a complete local SQLite backup beside the database as `applications.sqlite3.pre-migration-*.sqlite3`. The backup retains legacy portal names.

Update the CSV as each batch of employers is verified, then rerun the seed command. For every employer, record an India software, AI or embedded software role in `engineering_role` and its evidence in `role_source`. For non-YC companies, record reported India graduate or entry-level technical compensation above ₹15 LPA and a plain-text source. These figures can reflect individual offers, campus packages or entry-level pay ranges. For YC-backed companies, record the YC profile and evidence of an Indian location. They have no pay cutoff. Check the portal for an active opening and verify that role's eligibility and compensation before applying.
