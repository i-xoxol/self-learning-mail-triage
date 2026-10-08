"""Query historical case memory while printing metadata only, not message excerpts."""

from __future__ import annotations

import argparse
import json

from mailbox_graph import authentication_status
from playbook_store import PlaybookStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--include-redacted-excerpts", action="store_true")
    args = parser.parse_args()
    status = authentication_status()
    if not status.get("authenticated"):
        raise SystemExit(status.get("reason") or "Microsoft Graph authentication unavailable")
    mailbox = str(status["mailbox"])
    with PlaybookStore() as store:
        cases = store.search_cases(
            mailbox,
            args.query,
            limit=min(max(args.limit, 1), 10),
            max_age_days=min(max(args.days, 1), 3650),
        )
    safe = []
    for item in cases:
        record = {
            "id": item["id"],
            "topic": item["topic"],
            "course": item["course"],
            "sender_role": item["sender_role"],
            "resolved_at": item["resolved_at"],
            "score": item["score"],
            "confidence": item["confidence"],
            "matched_terms": item["matched_terms"],
            "warnings": item["warnings"],
        }
        if args.include_redacted_excerpts:
            record["subject"] = item["subject"]
            record["inbound_excerpt"] = item["inbound_excerpt"]
            record["final_response_excerpt"] = item["final_response_excerpt"]
        safe.append(record)
    print(json.dumps({"mailbox": mailbox, "query": args.query, "count": len(safe), "cases": safe}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
