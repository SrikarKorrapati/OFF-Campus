# Job application workflow

The daily automation runs `.venv/bin/python -m job_tracker.daily_scan` from the project root. Python starts a separate Codex session per source, with up to four source sessions open at once. Each session can use up to 36 native job subagents. Each agent uses its own browser tab. A source hands matching openings to its children while it continues searching. [Python entry point](../job_tracker/daily_scan.py)

## Company careers pages

Python selects every shortlisted company never checked or last checked at least 72 hours ago. Its agent verifies the official careers page, finds it if the saved URL is missing or incorrect, and checks all active openings against the [job requirements](job_requirements.md). The verified careers URL is the discovery source. Python saves the URL and scan time after a complete scan, including a scan with zero matches.

## Daily portal scan

After the company sessions finish, Python starts a session per job board. Each scans postings from its saved cutoff (inclusive) to the shared UTC start time (exclusive). A first scan looks back 14 days. The portal agent verifies ambiguous dates and passes the board URL to each job worker as the discovery source. [Job portals](job_sources.md)

## WhatsApp channels

WhatsApp runs once in its own session after the job boards. Its agent visits every followed channel it can discover and hands off each distinct job link with the discovery source `WhatsApp`. Each channel resumes from its own checkpoint, or 14 days before the scan start on the first visit. [Channel scan](../.agents/skills/whatsapp-job-scan/SKILL.md)

## Apply

The job subagent opens its own tab, verifies the opening and requisition ID on the employer's site, and checks eligibility. Only the worker that wins the atomic `claim_job` fills the form. It uses the candidate profile for identity fields and the writer–critic graph for the remaining questions. It submits once, records the submitted answers and outcome in the tracker, and checks Gmail for confirmation. Uncertain submissions need reconciliation before a retry. [Job agent instructions](../.codex/agents/job_application.toml)

## Saving progress

Python waits for the session's job results and checks reported submissions against SQLite. A complete scan accounts for every match as applied, already applied, closed or ineligible. Blocked or partial work leaves the source due. WhatsApp can advance a completed channel while another channel remains due. If the CLI cannot reach the connected browser, Python reports the blocker and stops launching new sources. [Source selection and checkpoints](../job_tracker/scan_sources.py)
