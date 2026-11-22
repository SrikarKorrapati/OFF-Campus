# Job sources

Search for India-based openings and filter by posting date where available. Use the [application workflow](application_workflow.md) to verify a listing before applying.

## Startups and technology

| Portal | Best for |
| --- | --- |
| [Y Combinator (YC)](https://www.ycombinator.com/jobs/role/all/india) | Engineering, product, and other roles at YC-backed startups in India |
| [Wellfound](https://wellfound.com/location/india) | Startup and tech roles. Use the India filter for its international and remote listings. |
| [Cutshort](https://cutshort.io/jobs) | Tech and tech-adjacent roles |
| [Hirist](https://www.hirist.tech/) | IT and technology roles |
| [DevsUnite](https://devsunite.com/jobs) | Early-career software roles and internships. Check the location on international and remote listings. |

## Internships and graduate roles

| Portal | Best for |
| --- | --- |
| [Internshala](https://internshala.com/jobs/) | Internships and entry-level jobs |
| [Freshersworld](https://www.freshersworld.com/freshers) | First jobs, walk-ins, and graduate roles |

## General job boards

| Portal | Best for |
| --- | --- |
| [LinkedIn Jobs](https://in.linkedin.com/jobs/fresher-entry-level-jobs) | Broad entry-level roles, networking, and recruiter visibility |
| [Naukri](https://www.naukri.com/fresher-jobs-in-india) | Private-sector fresher roles |
| [Indeed India](https://in.indeed.com/Fresher-jobs-in-India) | Fresher roles across employers and industries |
| [Foundit](https://www.foundit.in/search/fresher-jobs-in-india) | Broad roles across experience levels |
| [Shine](https://www.shine.com/job-search/fresher-jobs) | Entry-level jobs across fields |

## Channels

[WhatsApp Web](https://web.whatsapp.com/) · Assign one portal agent to the [WhatsApp channel scan skill](../.agents/skills/whatsapp-job-scan/SKILL.md). It discovers job links across all followed channels in the signed-in profile.

## Run the portals in Codex

The daily automation applies to new openings that match the [job requirements](job_requirements.md). Use the connected browser profile. Each worker opens its own tab. An explicit search-only run returns verified openings and leaves the application checkpoints unchanged.

1. **Start the scan.** From `job_tracker.database`, call `initialize()` and read `SELECT id, name, last_accessed_at FROM job_portals ORDER BY id` with `query_the_schema`. Capture one UTC start time with `date -u +%Y-%m-%dT%H:%M:%SZ`. Start one worker per portal, passing its row, source link, run mode and start time. Queue workers when all slots are in use.
2. **Find new openings.** On each job board, cover postings from its saved time (inclusive) to the run start (exclusive). For a NULL time, use the fixed start date in the daily automation so a missed first run still catches up. Include overlapping date labels and check dates on the employer's site when needed. If the posting date cannot be placed in the window using either site, report it for follow-up. WhatsApp uses the channel checkpoints in its linked skill.
3. **Apply in parallel.** Start a job worker for each match while the portal worker continues searching. Pass the listing URL and discovery source (the job board URL or `WhatsApp`). Verify eligibility and the requisition ID on the employer’s site. In application mode, only the worker that wins `claim_job(company_name, job_id)` fills, submits and records the outcome using the [application workflow](application_workflow.md).
4. **Save progress.** Wait for the portal’s job workers. On a complete application scan, call `record_job_portal_scan(portal_id, scan_started_at)` with the original start time, even for zero matches. A scan is complete when every candidate was applied to, already applied to, closed or ruled ineligible. Leave the old time on blocked, partial or unresolved work so the next run can retry. Reconcile any interrupted submission against the employer portal or confirmation email before retrying it. Report applications and outstanding work by portal.
