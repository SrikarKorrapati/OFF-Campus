# Application deliverables

| Output | What to record or report |
| --- | --- |
| Eligible openings | Active private-sector roles in India that meet the six-month internship or full-time criteria in `docs/job_requirements.md`. |
| Company shortlist | One company row per eligible employer, with its normalized name and careers URL when known. After a portal check, `last_checked_at` records the check time. |
| Submitted applications | One record per confirmed submission in `applied_jobs/applications.sqlite3`, with employer name, job name, requisition ID, job link, source portal URL, submission time, and all application questions and answers except verification codes. |
| Email confirmation | Whether Gmail received a confirmation email for each submitted application. |

Follow the [application workflow](general_instructions.md) to produce these records.
