"""Look up application history in the local tracker."""

import argparse
import json

from .history import get_company_status, has_applied_to_company, list_recently_applied_companies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recent = commands.add_parser("recent", help="List companies applied to in the last HOURS hours")
    recent.add_argument("hours", type=float, metavar="HOURS")
    applied = commands.add_parser("applied", help="Check whether an application was submitted to COMPANY")
    applied.add_argument("company", metavar="COMPANY")
    status = commands.add_parser("status", help="Show the tracker status for COMPANY")
    status.add_argument("company", metavar="COMPANY")

    args = parser.parse_args()
    try:
        if args.command == "recent":
            result = list_recently_applied_companies(args.hours)
        elif args.command == "applied":
            result = has_applied_to_company(args.company)
        else:
            result = get_company_status(args.company)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
