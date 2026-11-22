# Job application workflow

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

1. Visit each selected employer’s official careers page, queuing companies as worker slots fill. If the URL is missing or points to the wrong employer, find the careers page through the employer’s website and use the verified link for this scan. If the page cannot be verified or accessed, report the company and keep it due.
2. Check all active openings on that page against the job requirements. In application mode, call `claim_job(company_name, job_id)` for each eligible opening. Only the worker that claims it proceeds with the application steps below. Save the careers page as the discovery source and the individual opening URL as `job_link`.
3. After a full company scan in application mode, save any new or corrected careers URL with `add_company_portal(company_name, career_page_url)`, then call `record_company_portal_check(company_name)` once. Do this even for zero matches. A scan is complete when every opening was applied to, already applied to, closed or ruled ineligible. Keep the previous timestamp for blocked or unresolved work. Wait for every selected company worker to finish or report a blocker before starting the job portals.

## Daily portal scan

1. **Start the scan.** Read `SELECT id, name, last_accessed_at FROM job_portals ORDER BY id` with `query_the_schema`. Capture one UTC start time with `date -u +%Y-%m-%dT%H:%M:%SZ`. Start one worker per portal, passing its row, link from the [source list](job_sources.md), run mode and start time. Queue workers when all slots are in use.
2. **Find new openings.** On each job board, cover postings from its saved time (inclusive) to the run start (exclusive). For a NULL time, use the fixed start date in the daily automation so a missed first run still catches up. Include overlapping date labels and check dates on the employer's site when needed. If the posting date cannot be placed in the window using either site, report it for follow-up. For WhatsApp, follow the [channel scan skill](../.agents/skills/whatsapp-job-scan/SKILL.md) to scan followed channels from their saved times.
3. **Apply in parallel.** Start a job worker for each match while the portal worker continues searching. Pass the listing URL and discovery source (the job board URL or `WhatsApp`). Verify eligibility and the requisition ID on the employer’s site. In application mode, only the worker that wins `claim_job(company_name, job_id)` fills, submits and records the outcome using the application steps below.
4. **Save progress.** Wait for the portal’s job workers. On a complete application scan, call `record_job_portal_scan(portal_id, scan_started_at)` with the original start time, even for zero matches. A scan is complete when every candidate was applied to, already applied to, closed or ruled ineligible. Leave the old time on blocked, partial or unresolved work so the next run can retry. Reconcile any interrupted submission against the employer portal or confirmation email before retrying it. Report applications and outstanding work by portal.

[Shortlist employers](job_requirements.md#shortlist-employers) → Verify an opening → Check for a previous submission → Complete the form → Save the outcome → Check Gmail.

## Apply

When creating a job portal account or signing back into that account, enter `JOB_PORTAL_PASSWORD` from the project’s local `.env` in the verified portal’s password field. Keep the value out of model prompts and application records.

1. Check each opening against the [job requirements](job_requirements.md). Before sharing personal details, confirm the opening is active on the employer’s careers page.
2. Look up the employer and requisition ID in the tracker. Skip openings already marked `applied`.
3. Fill known contact and identity fields from the candidate profile. Build the question graph once per application. Send the remaining independent questions on each page together, keyed by stable field ID, with their displayed options and character limits. Fill approved answers by ID. After a choice, read the live form again, discard answers for hidden or changed fields, and send newly revealed questions in the next batch. Ask for missing facts on unresolved required fields. [Batch inputs and outputs](../job_tracker/README.md#question-workflow)
4. Read email verification codes with `gws`. Enter each code only in the verification field and omit it from saved answers. Follow browser prompts for verification, CAPTCHAs and submission.
5. Save the opening, discovery source and application Q&A. Mark a confirmed submission `applied`, then check Gmail for the confirmation and report whether it arrived. Mark a failed attempt `failed_to_apply` and explain why. Use up to five short, single-line status notes. [Tracker fields](../job_tracker/README.md#application-records)
