"""Read or advance a followed WhatsApp channel's UTC scan checkpoint."""

import argparse
from datetime import datetime, timedelta
import fcntl
import json
from pathlib import Path

STATE = Path(__file__).resolve().parents[4] / "job_tracker/whatsapp_scan/last_checked.json"
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def checkpoint(path: Path, action: str, channel: str, started: datetime) -> str:
    if action == "since":
        return load(path).get(channel, (started - timedelta(days=14)).strftime(UTC_FORMAT))

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A separate lock survives replacing the JSON file and is released if the worker exits.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load(path)
        stamp = max(started.strftime(UTC_FORMAT), state.get(channel, ""))
        state[channel] = stamp
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return stamp


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("since", "complete"))
    parser.add_argument("channel", help="Stable WhatsApp channel identifier")
    parser.add_argument("started", type=lambda value: datetime.strptime(value, UTC_FORMAT),
                        help="Scan start in UTC, in YYYY-MM-DDTHH:MM:SSZ format")
    args = parser.parse_args()
    if not args.channel.strip():
        parser.error("Provide a channel identifier.")
    print(checkpoint(STATE, args.action, args.channel, args.started))
