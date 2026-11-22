"""Apply to one open Lever posting using the existing question graph."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import UUID

from langchain_openai import ChatOpenAI
from playwright.sync_api import Error as BrowserError, Page, sync_playwright

from applied_jobs.store import (
    DATABASE, add_company_portal, initialize, normalize_name, record_company_portal_check, save_application,
)
from lever_form import fill_application_form
from question_graph import build_question_graph


def gmail_receipt(job_url: str, since: int) -> bool | None:
    """Look for a recent Lever acknowledgment that identifies this exact opening."""
    job_id = job_url.rsplit("/", 1)[1]
    query = (f'after:{since - 1} from:no-reply@hire.lever.co "{job_id}" '
             '{subject:"application received" subject:"thank you for applying" subject:"thank you for your application"}')
    try:
        result = subprocess.run(
            ["gws", "gmail", "users", "messages", "list", "--params",
             json.dumps({"userId": "me", "q": query, "maxResults": 1})],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return bool(json.loads(result.stdout).get("messages"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _already_applied(database: Path, company: str, job_id: str) -> bool:
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(
            "SELECT 1 FROM applications WHERE company_name=? AND job_id=? AND status='applied'",
            (normalize_name(company), job_id),
        ).fetchone() is not None


def _finish(pending: Path, database: Path, *, portal_confirmed: bool = False) -> dict:
    # Keep the attempted answers until a receipt is found, including across restarts.
    try:
        with pending.open(encoding="utf-8") as file:
            attempt = json.load(file)
            since = int(os.fstat(file.fileno()).st_mtime)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "submission_unconfirmed", "reason": "Check the prior submission before retrying."}
    if _already_applied(database, attempt["company_name"], attempt["job_id"]):
        pending.unlink(missing_ok=True)
        return {"status": "already_applied"}
    email = None if portal_confirmed else gmail_receipt(attempt["job_link"], since)
    if not portal_confirmed and not email:
        return {"status": "submission_unconfirmed", "gmail_confirmed": email}
    save_application(**attempt, status="applied", database=database)
    pending.unlink(missing_ok=True)
    if portal_confirmed:
        email = gmail_receipt(attempt["job_link"], since)
    return {"status": "applied", "gmail_confirmed": email}


def apply_to_job(job_url: str, source_portal_url: str, *, page: Page, graph, resume_path: Path | None = None,
                 resume_text: str = "", database: Path = DATABASE) -> dict:
    url = urlsplit(job_url)
    path = re.fullmatch(r"/([\w-]+)/([\da-fA-F-]{36})(?:/apply)?/?", url.path)
    if url.scheme != "https" or url.netloc not in ("jobs.lever.co", "jobs.eu.lever.co") or not path:
        raise ValueError("Provide a direct HTTPS Lever job posting URL.")
    source = urlsplit(source_portal_url)
    if source.scheme not in ("https", "http") or not source.hostname:
        raise ValueError("Provide the URL where you found the job.")
    board = f"https://{url.netloc}/{path[1]}"
    job_id = str(UUID(path[2]))
    listing = f"{board}/{job_id}"
    pending = database.with_name(f"{database.name}.{path[1]}.{job_id}.pending.json")
    if pending.exists():
        return _finish(pending, database)

    response = page.goto(listing + ("?" + url.query if url.query else ""), wait_until="domcontentloaded")
    if response and (response.status in (404, 410) or page.url.rstrip("/") == board):
        return {"status": "closed"}
    if not response or not response.ok or page.url.split("?")[0].rstrip("/") != listing:
        return {"status": "needs_input", "reason": "Could not verify the employer’s listing."}
    metadata = page.locator('script[type="application/ld+json"]')
    posting = next((item for item in map(json.loads, metadata.all_text_contents())
                    if isinstance(item, dict) and item.get("@type") == "JobPosting"), {})
    company = posting.get("hiringOrganization", {}).get("name")
    title = posting.get("title")
    apply_url = listing + "/apply"
    link = page.locator('a[data-qa="show-page-apply"], a[href$="/apply"]').first
    href = urljoin(listing, link.get_attribute("href") or "") if link.count() else ""
    if not company or not title or href.split("?")[0] != apply_url:
        return {"status": "needs_input", "reason": "Could not verify an active Apply link and job details."}

    with closing(sqlite3.connect(initialize(database))) as connection:
        portal = connection.execute("SELECT career_page_url FROM applications WHERE company_name=? AND job_id IS NULL",
                                    (normalize_name(company),)).fetchone()
    if not portal or not portal[0]:
        add_company_portal(company, board, database=database)
    record_company_portal_check(company, database=database)
    if _already_applied(database, company, job_id):
        return {"status": "already_applied"}

    response = page.goto(href, wait_until="domcontentloaded")
    form = page.locator("form#application-form")
    if not response or not response.ok or page.url.split("?")[0] != apply_url or not form.is_visible():
        return {"status": "needs_input", "reason": "The application form is unavailable."}
    if urljoin(page.url, form.get_attribute("action") or page.url).split("?")[0] != apply_url:
        return {"status": "needs_input", "reason": "Unexpected form submission destination."}
    answers = []
    reason = fill_application_form(form, graph, company=company, job_id=job_id, answers=answers,
                                   resume_path=resume_path, resume_text=resume_text)
    if reason:
        return {"status": "needs_input", "reason": reason}
    submit = form.locator("#btn-submit")
    if not submit.is_visible() or not submit.is_enabled():
        return {"status": "needs_input", "reason": "The Submit button is unavailable."}
    attempt = dict(company_name=company, job_id=job_id, job_name=title, job_link=listing,
                   source_portal_url=source_portal_url, questions_answers=answers)
    try:
        with open(pending, "x", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
            json.dump(attempt, file)
    except FileExistsError:
        return {"status": "submission_unconfirmed", "reason": "This opening already has a submission in progress."}
    if _already_applied(database, company, job_id):
        pending.unlink(missing_ok=True)
        return {"status": "already_applied"}
    try:
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.split("?")[0] == apply_url,
                                  timeout=60000) as submitted:
            submit.click()
        reply = submitted.value
        destination = urlsplit(urljoin(apply_url, reply.headers.get("location", "")))
        receipt_id = parse_qs(destination.query).get("LeverAppId", [""])[0]
        if (reply.request.is_navigation_request() and 300 <= reply.status < 400
                and destination.scheme == "https" and destination.netloc != url.netloc
                and re.fullmatch(r"[\da-fA-F]{8}(?:-[\da-fA-F]{4}){3}-[\da-fA-F]{12}", receipt_id)):
            return _finish(pending, database, portal_confirmed=True)
        page.wait_for_url(lambda url: url.split("?")[0].rstrip("/") == listing + "/thanks", timeout=15000)
        page.get_by_role("heading", name="Application submitted!", exact=True).wait_for(timeout=5000)
    except BrowserError:
        if not page.is_closed() and page.url.split("?")[0] == apply_url:
            invalid = form.locator(":user-invalid:visible, [aria-invalid=true]:visible, .error-message:visible").first
            if invalid.is_visible():
                message = invalid.evaluate("el => el.validationMessage || el.innerText || 'Invalid field'")
                reason = " ".join(message.split()) or "Invalid field"
                save_application(**attempt, status="failed_to_apply", status_notes=[reason], database=database)
                pending.unlink(missing_ok=True)
                return {"status": "failed_to_apply", "reason": reason}
        return _finish(pending, database)
    return _finish(pending, database, portal_confirmed=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_url")
    parser.add_argument("--source", help="Discovery URL, defaults to the posting itself")
    parser.add_argument("--resume", type=Path, help="Résumé file to attach")
    parser.add_argument("--resume-text", type=Path, help="Plain text of the résumé for the answer agent")
    args = parser.parse_args()
    if args.resume and not args.resume.is_file():
        parser.error("The résumé file does not exist.")
    if not os.getenv("OPENAI_MODEL") or not os.getenv("OPENAI_API_KEY"):
        parser.error("Set OPENAI_MODEL and OPENAI_API_KEY before running.")
    graph = build_question_graph(ChatOpenAI(model=os.environ["OPENAI_MODEL"]))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        result = apply_to_job(args.job_url, args.source or args.job_url, page=browser.new_page(), graph=graph,
                              resume_path=args.resume, resume_text=args.resume_text.read_text() if args.resume_text else "")
        print(json.dumps(result))
