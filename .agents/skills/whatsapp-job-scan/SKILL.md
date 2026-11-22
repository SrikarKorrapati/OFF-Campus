---
name: whatsapp-job-scan
description: Scan followed WhatsApp Web channels for job links during this project's daily application workflow.
---

# Scan followed WhatsApp channels

Use the signed-in WhatsApp Web profile and visit every followed channel shown in Channels. Scroll to the end of the channel list. Use each channel's stable ID to look up its cutoff supplied by Python. An unseen channel starts 14 days before the scan start. Include posts from the cutoff (inclusive) to the scan start (exclusive), allowing for rounded timestamps in the browser's timezone.

Hand each distinct opening to the session's job worker with `WhatsApp` as the discovery source and the actual opening URL as `job_link`. Report coverage and job outcomes per channel, including empty or blocked channels. Python records each completed channel's checkpoint. [WhatsApp workflow](../../../docs/application_workflow.md#whatsapp-channels)
