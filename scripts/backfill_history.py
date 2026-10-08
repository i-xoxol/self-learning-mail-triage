"""Run the explicit one-time historical case-memory import."""

from __future__ import annotations

import argparse
import json

from historical_backfill import backfill_historical_cases
from mailbox_graph import graph
from playbook_store import PlaybookStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--max-sent", type=int, default=10_000)
    parser.add_argument("--max-mailbox-messages", type=int, default=30_000)
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    if not args.confirmed:
        parser.error("--confirmed is required because this stores redacted historical cases locally")
    if not 30 <= args.days <= 3650:
        parser.error("--days must be between 30 and 3650")
    if not 1 <= args.max_sent <= 50_000 or not 1 <= args.max_mailbox_messages <= 100_000:
        parser.error("message limits are outside the allowed range")
    client, mailbox = graph()
    with PlaybookStore() as store:
        result = backfill_historical_cases(
            client,
            mailbox,
            store,
            days=args.days,
            max_sent=args.max_sent,
            max_mailbox_messages=args.max_mailbox_messages,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
