---
name: whatsapp-job-scan
description: Find job links in followed WhatsApp Web channels since their last successful scan and hand them to this project's job workflow.
---

# Scan followed WhatsApp channels

1. From the repository root, set `scan_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)` once. Open WhatsApp Web in the connected, signed-in browser profile. In **Channels**, scroll through the followed list to its end and visit every followed channel. Set `channel_id` to the stable identifier from that channel's link or channel info.
2. For each channel, run `python3 .agents/skills/whatsapp-job-scan/scripts/checkpoint.py since "$channel_id" "$scan_start"`. An unseen channel starts 14 days before this run. Read posts back to that cutoff or the visible beginning of the channel. Extract job URLs from posts at or after the cutoff and before the scan start. Interpret displayed times in the browser's timezone and include posts that overlap a boundary when WhatsApp rounds the time.
3. Hand each distinct job URL to a job child through the [existing portal workflow](../../../docs/job_portals.md#run-the-portals-in-codex), preserving the user's search or application mode. Pass the literal `WhatsApp` as `source_portal_url`. The verified opening URL belongs in `job_link`. The child handles eligibility, verification and duplicate checks.
4. Once the interval is covered and the workflow has accepted every link (or there were none), run `python3 .agents/skills/whatsapp-job-scan/scripts/checkpoint.py complete "$channel_id" "$scan_start"`. An interrupted scan, missing history or failed handoff leaves that channel at its previous cutoff. Continue with other channels and report any left incomplete.

The helper keeps the local channel-ID-to-UTC-time mapping in `applied_jobs/whatsapp_scan/last_checked.json`.
