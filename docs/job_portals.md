# Job Portal Links

Search for India-based openings and filter by posting date where available. Use the [application workflow](general_instructions.md) to verify a listing before applying.

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

## Run the portals in Codex

Use Codex subagents in the connected, active browser profile. Pass the user's search or application request to every worker. Each worker opens its own tab and targets that tab by ID.

1. **Coordinator.** Read the portal links above at the start of each run. Start one subagent per distinct portal in parallel. Leave slots for job subagents. If the session is full, start queued work as slots become available.
2. **Portal subagent.** Search your assigned portal using the [job requirements](job_requirements.md). As you find matching openings, spawn one child per opening with its listing URL and discovery URL. Start siblings concurrently and continue searching while they work. Report a blocked portal so the others can continue.
3. **Job subagent.** Verify the role and requisition ID on the employer's listing. For a search, return the verified opening. For an application run, call `claim_job(company_name, job_id)` once for the duplicate check in the [application workflow](general_instructions.md). Only the worker receiving `claimed: true` continues in its own tab to fill, submit and record the application on the employer's actual portal.
4. **Completion.** Each portal agent waits for its job children. The coordinator collects every portal's result, merges duplicate openings by employer and requisition ID, and reports the outcomes, including portals with zero matches or blocked access.
