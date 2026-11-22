# Application workflow

The daily automation checks shortlisted companies’ careers pages first, then searches job portals. Use the connected browser profile and the [job requirements](job_requirements.md) in both phases. Each worker opens its own tab. An explicit search-only run returns verified openings and leaves the scan timestamps unchanged.

## Company careers pages

From `job_tracker.database`, call `initialize()` and run this query once with `query_the_schema` to select every employer never checked or last checked at least 72 hours ago.

```sql
SELECT company_name, career_page_url
FROM applications
WHERE job_id IS NULL
  AND (last_checked_at IS NULL OR datetime(last_checked_at) <= datetime('now', '-3 days'))
ORDER BY last_checked_at, company_name;
```

1. Visit each selected employer’s official careers page, queuing companies as worker slots fill. If the URL is missing or points to the wrong employer, find the careers page through the employer’s website and save it with `add_company_portal(company_name, career_page_url)`. If the page cannot be verified or accessed, report the company and keep it due.
2. Check all active openings on that page against the job requirements. In application mode, call `claim_job(company_name, job_id)` for each eligible opening. Only the worker that claims it proceeds with the application steps below. Save the careers page as the discovery source and the individual opening URL as `job_link`.
3. After a full company scan in application mode, call `record_company_portal_check(company_name)` once, including when there are zero matches. A scan is complete when every opening was applied to, already applied to, closed or ruled ineligible. Keep the previous timestamp for blocked or unresolved work. Wait for every selected company worker to finish or report a blocker before starting the job portals.

## Daily portal scan

1. **Start the scan.** Read `SELECT id, name, last_accessed_at FROM job_portals ORDER BY id` with `query_the_schema`. Capture one UTC start time with `date -u +%Y-%m-%dT%H:%M:%SZ`. Start one worker per portal, passing its row, link from the [source list](job_sources.md), run mode and start time. Queue workers when all slots are in use.
2. **Find new openings.** On each job board, cover postings from its saved time (inclusive) to the run start (exclusive). For a NULL time, use the fixed start date in the daily automation so a missed first run still catches up. Include overlapping date labels and check dates on the employer's site when needed. If the posting date cannot be placed in the window using either site, report it for follow-up. For WhatsApp, follow the [channel scan skill](../.agents/skills/whatsapp-job-scan/SKILL.md) to scan followed channels from their saved times.
3. **Apply in parallel.** Start a job worker for each match while the portal worker continues searching. Pass the listing URL and discovery source (the job board URL or `WhatsApp`). Verify eligibility and the requisition ID on the employer’s site. In application mode, only the worker that wins `claim_job(company_name, job_id)` fills, submits and records the outcome using the application steps below.
4. **Save progress.** Wait for the portal’s job workers. On a complete application scan, call `record_job_portal_scan(portal_id, scan_started_at)` with the original start time, even for zero matches. A scan is complete when every candidate was applied to, already applied to, closed or ruled ineligible. Leave the old time on blocked, partial or unresolved work so the next run can retry. Reconcile any interrupted submission against the employer portal or confirmation email before retrying it. Report applications and outstanding work by portal.

Reuse confirmed answers and handle routine steps independently. Ask only for a missing fact, decision, or action.

## Shortlist criteria

Select private-sector employers with in-house engineering teams that build their own products, infrastructure, or technology. Exclude services-led consultancies, engineering outsourcers, staffing firms, and government or public-sector undertakings.

| Employer | Evidence to record in the local CSV |
| --- | --- |
| All | Record an India-based software, AI, embedded, forward-deployed, or related hands-on engineering role in `engineering_role` and its source in `role_source`. |
| Non-YC | Record reported total CTC above ₹15 LPA for an India-based graduate or entry-level technical role in `reported_ctc_lpa`. Give a plain-text reference in `salary_source`. |
| YC-backed | Record the YC profile in `yc_profile_url`, the Indian office location in `india_office`, and the source for that location in `india_office_source`. The company-level pay cutoff is waived. |

## Find and verify openings

1. Search for active private-sector openings in India that offer a six-month internship or a full-time role. Apply the location, availability, pay, employer exclusions, and approved exceptions in `docs/job_requirements.md`. [Job portals](job_sources.md)
2. Add each verified employer once to the local `job_tracker/company_shortlist.csv` and register it with `add_company_portal(company_name, career_page_url)` from `job_tracker.database`. Use uppercase company names with underscores between words. Leave the careers URL blank if unknown. Git ignores seed CSVs.
3. Confirm the opening on the employer's careers page before sharing personal information or applying. Verify eligibility and pay for that opening.

## Apply and confirm

When creating a job portal account or signing back into that account, enter `JOB_PORTAL_PASSWORD` from the project’s local `.env` in the verified portal’s password field. Keep the value out of model prompts and application records.

1. Before applying, check the tracker for a confirmed submission using the employer name and requisition ID. Skip openings already marked `applied`.
2. Use the LangGraph workflow for each field. Give it `docs/candidate_profile.md`, the résumé, and `docs/job_requirements.md`. Write a natural, specific answer and fill the field only once the critic approves it, with up to three answer attempts.
3. For an email OTP, read the matching Gmail message through the authorized GWS CLI. Enter the code only in the portal's verification field and keep it out of saved answers. Follow the browser's confirmation prompts for OTP entry, each CAPTCHA, and final submission.
4. Save one record per employer and requisition ID in `job_tracker/applications.sqlite3`. Include the job name, job link, discovery source, and application questions and answers. Mark a confirmed submission `applied` and record its submission time in `applied_at`. If the attempt ends before submission, record `failed_to_apply` and explain why. Use up to five short, single-line bullets for status notes.
5. For each confirmed submission, check Gmail through the GWS CLI and report whether the confirmation email arrived. If Gmail access or verification is blocked, request the missing action and resume once it is complete.
