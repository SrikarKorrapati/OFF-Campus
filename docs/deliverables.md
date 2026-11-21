# Application deliverables

| Output | What to record or report |
| --- | --- |
| Eligible openings | Active private-sector roles in India that meet the six-month internship or full-time criteria in `docs/job_requirements.md`. |
| Company shortlist | One company row per eligible employer, with its normalized name and careers URL when known. After a portal check, `last_checked_at` records the check time. |
| Application attempts | One record per employer and requisition ID in `applied_jobs/applications.sqlite3`, with the job name, job link, source portal URL, and application questions and answers except verification codes. Record the submission time for `applied`. For `failed_to_apply`, record one to five concise reasons. |
| Email confirmation | Whether Gmail received a confirmation email for each submitted application. |

Follow the [application workflow](general_instructions.md) to produce these records.
