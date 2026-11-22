"""Read or advance a followed WhatsApp channel's UTC scan checkpoint."""

import argparse
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from job_tracker.database import UTC_FORMAT, whatsapp_channel_checkpoint


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("since", "complete"))
    parser.add_argument("channel", help="Stable WhatsApp channel identifier")
    parser.add_argument("started", type=lambda value: datetime.strptime(value, UTC_FORMAT),
                        help="Scan start in UTC, in YYYY-MM-DDTHH:MM:SSZ format")
    args = parser.parse_args()
    if not args.channel.strip():
        parser.error("Provide a channel identifier.")
    print(whatsapp_channel_checkpoint(args.channel, args.started, complete=args.action == "complete"))
