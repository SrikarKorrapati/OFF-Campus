---
name: whatsapp-job-scan
description: Find job links in followed WhatsApp Web channels since their last successful scan and hand them to this project's job workflow.
---

# Scan followed WhatsApp channels

1. Use the coordinator’s UTC `scan_start`, or set `scan_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)` once when scanning independently. Open WhatsApp Web in the connected, signed-in browser profile. In **Channels**, scroll through the followed list to its end and visit every followed channel. Set `channel_id` to the stable identifier from that channel's link or channel info.
2. For each channel, run `python3 .agents/skills/whatsapp-job-scan/scripts/checkpoint.py since "$channel_id" "$scan_start"`. An unseen channel starts 14 days before this run. Read posts back to that cutoff or the visible beginning of the channel. Extract job URLs from posts at or after the cutoff and before the scan start. Interpret displayed times in the browser's timezone and include posts that overlap a boundary when WhatsApp rounds the time.
3. Hand each distinct job URL to a job child through the [existing portal workflow](../../../docs/application_workflow.md#daily-portal-scan), preserving the user's search or application mode. Pass the literal `WhatsApp` as `source_portal_url`. The verified opening URL belongs in `job_link`. The child handles eligibility, verification and duplicate checks.
4. In application mode, once the interval is covered and every job child has finished with an outcome that completes the portal workflow (or there were no links), run `python3 .agents/skills/whatsapp-job-scan/scripts/checkpoint.py complete "$channel_id" "$scan_start"`. Keep the previous cutoff on a search-only run or when history, a handoff or an application is incomplete. Continue with other channels and report any left incomplete.

The helper stores each channel’s UTC scan start in `whatsapp_channels(channel_id, last_checked_at)` in `job_tracker/applications.sqlite3`.
