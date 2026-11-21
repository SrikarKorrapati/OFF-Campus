"""Load eligible companies into the local applications table."""
import csv
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from .store import DATABASE, add_company_portals, normalize_name
else:
    from store import DATABASE, add_company_portals, normalize_name


SEED_FILE = Path(__file__).with_name("company_seed.csv")
EXCLUDED = {"MASTERCARD", "RUBRIK"}


def seed_company_portals(database: Path = DATABASE, *, seed_file: Path = SEED_FILE) -> int:
    with seed_file.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        headers = set(reader.fieldnames or ())
        required = {"company_name", "career_page_url", "reported_ctc_lpa"}
        if not required <= headers or not headers & {"salary_source", "salary_source_url"}:
            raise ValueError("Seed requires company_name, career_page_url, reported_ctc_lpa and a salary source")
        companies = list(reader)

    seen = set()
    for company in companies:
        name = company["company_name"]
        if not name or name != normalize_name(name) or name in EXCLUDED or name in seen:
            raise ValueError(f"Invalid, excluded or duplicate company: {name}")
        seen.add(name)
        if company.get("yc_profile_url"):
            profile = urlsplit(company["yc_profile_url"])
            if (profile.hostname != "www.ycombinator.com" or not profile.path.startswith("/companies/")
                    or not company.get("india_office") or not company.get("india_office_source")):
                raise ValueError(f"Missing YC or India office evidence for {name}")
        else:
            pay = Decimal(company["reported_ctc_lpa"] or "0")
            if not pay.is_finite() or pay <= 15 or not (company.get("salary_source") or company.get("salary_source_url")):
                raise ValueError(f"Missing fresher compensation above 15 LPA for {name}")
        url = company["career_page_url"]
        if url and (urlsplit(url).scheme not in {"https", "http"} or not urlsplit(url).hostname):
            raise ValueError(f"Invalid careers URL for {name}")

    add_company_portals(((row["company_name"], row["career_page_url"]) for row in companies), database=database)
    return len(companies)


if __name__ == "__main__":
    print(f"Loaded {seed_company_portals()} companies")
