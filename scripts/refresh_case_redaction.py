"""Reapply current redaction rules to stored case excerpts without reading Outlook."""

from __future__ import annotations

import json

from mailbox_graph import authentication_status
from playbook_store import PlaybookStore


def main() -> int:
    status = authentication_status()
    if not status.get("authenticated"):
        raise SystemExit(status.get("reason") or "Microsoft Graph authentication unavailable")
    mailbox = str(status["mailbox"])
    with PlaybookStore() as store:
        changed = store.refresh_case_redaction(mailbox)
    print(json.dumps({"mailbox": mailbox, "cases_refreshed": changed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
