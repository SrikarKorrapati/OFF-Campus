# Application workflow

Reuse confirmed answers and handle routine steps independently. Ask only for a missing fact, decision, or action.

## Shortlist criteria

Select private-sector employers with in-house engineering teams that build their own products, infrastructure, or technology. Exclude services-led consultancies, engineering outsourcers, staffing firms, and government or public-sector undertakings.

| Employer | Evidence to record in the local CSV |
| --- | --- |
| All | Record an India-based software, AI, embedded, forward-deployed, or related hands-on engineering role in `engineering_role` and its source in `role_source`. |
| Non-YC | Record reported total CTC above ₹15 LPA for an India-based graduate or entry-level technical role in `reported_ctc_lpa`. Give a plain-text reference in `salary_source`. |
| YC-backed | Record the YC profile in `yc_profile_url`, the Indian office location in `india_office`, and the source for that location in `india_office_source`. The company-level pay cutoff is waived. |

## Find and verify openings

1. Search for active private-sector openings in India that offer a six-month internship or a full-time role. Apply the location, availability, pay, employer exclusions, and approved exceptions in `docs/job_requirements.md`. [Job portals](job_portals.md)
2. Add each verified employer once to the local `applied_jobs/company_seed.csv` and register it with `add_company_portal(company_name, career_page_url)` from `applied_jobs.store`. Use uppercase company names with underscores between words. Leave the careers URL blank if unknown. Git ignores seed CSVs.
3. Confirm the opening on the employer's careers page before sharing personal information or applying. Verify eligibility and pay for that opening. Call `record_company_portal_check(company_name)` to record the check time in `last_checked_at`.

## Apply and confirm

1. Before applying, check the tracker for a confirmed submission using the employer name and requisition ID. Skip openings already marked `applied`.
2. Use the LangGraph workflow for each field. Give it `docs/candidate_profile.md`, the résumé, and `docs/job_requirements.md`. Write a natural, specific answer and fill the field only once the critic approves it, with up to three answer attempts.
3. For an email OTP, read the matching Gmail message through the authorized GWS CLI. Enter the code only in the portal's verification field and keep it out of saved answers. Follow the browser's confirmation prompts for OTP entry, each CAPTCHA, and final submission.
4. Save one record per employer and requisition ID in `applied_jobs/applications.sqlite3`. Include the job name, job link, discovery source, and application questions and answers. Mark a confirmed submission `applied` and record its submission time in `applied_at`. If the attempt ends before submission, record `failed_to_apply` and explain why. Use up to five short, single-line bullets for status notes.
5. For each confirmed submission, check Gmail through the GWS CLI and report whether the confirmation email arrived. If Gmail access or verification is blocked, request the missing action and resume once it is complete.
