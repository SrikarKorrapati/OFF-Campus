# Application workflow

Reuse confirmed answers and handle routine steps independently. Ask only for a missing fact, decision, or action.

## Find and verify openings

1. Search the [job portals](job_portals.md) using the location, availability, pay, employer exclusions, and approved exceptions in your local `docs/job_requirements.md`.
2. Add verified employers to the shortlist CSV and load each batch into the tracker. [Shortlist criteria](../applied_jobs/README.md#shortlist-employers)
3. Confirm the opening on the employer's careers page before sharing personal information or applying. Record the check with `record_company_portal_check(company_name)`.

## Apply and confirm

1. Before applying through a portal or employer page, check for a previous submission using the employer name and requisition ID.
2. Use the LangGraph workflow for each field. Give it `docs/candidate_profile.md`, the résumé, and `docs/job_requirements.md`. Write a natural, specific answer and fill the field only once the critic approves it, with up to three answer attempts.
3. For an email OTP, read the matching Gmail message through the authorized GWS CLI. Enter the code only in the portal's verification field and keep it out of saved answers. Follow the browser's confirmation prompts for OTP entry, each CAPTCHA, and final submission.
4. Save a confirmed submission as `applied`. If an attempt ends before submission, record `failed_to_apply` with the reason so it can be retried. For confirmed submissions, check Gmail through the GWS CLI and report whether the confirmation email arrived. If Gmail access or verification is blocked, request the missing action and resume once it is complete. [Required records](deliverables.md)
