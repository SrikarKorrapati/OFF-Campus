---
name: whatsapp-job-scan
description: Find job links in followed WhatsApp Web channels since their last successful scan and hand them to this project's job workflow.
---

# Scan followed WhatsApp channels

1. Use the coordinator’s UTC `scan_start`, or set `scan_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)` once when scanning independently. Open WhatsApp Web in the connected, signed-in browser profile. In **Channels**, scroll through the followed list to its end and visit every followed channel. Set `channel_id` to the stable identifier from that channel's link or channel info.
2. For each channel, use `whatsapp_channels_sql` with `SELECT last_checked_at FROM whatsapp_channels WHERE channel_id = ?`, binding the channel ID. An empty result gives a cutoff of exactly 14 days before `scan_start`. Read posts back to that cutoff or the visible beginning of the channel. Extract job URLs from posts at or after the cutoff and before the scan start. Interpret displayed times in the browser's timezone and include posts that overlap a boundary when WhatsApp rounds the time.
3. Hand each distinct job URL to a job worker through the [daily portal scan](../../../docs/application_workflow.md#daily-portal-scan). Pass the literal `WhatsApp` as `source_portal_url`. The verified opening URL belongs in `job_link`. The worker verifies eligibility and applies to each opening it successfully claims.
4. Once the interval is covered and every job worker has finished with an outcome that completes the portal scan (or there were no links), use `whatsapp_channels_sql` with the upsert below, binding the channel ID and `scan_start`. Keep the previous cutoff when history, a handoff or an application is incomplete. Continue with other channels and report any left incomplete.

```sql
INSERT INTO whatsapp_channels (channel_id, last_checked_at) VALUES (?, ?)
ON CONFLICT (channel_id) DO UPDATE
SET last_checked_at = max(last_checked_at, excluded.last_checked_at);
```
