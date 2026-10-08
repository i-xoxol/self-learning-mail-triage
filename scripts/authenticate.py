"""Authenticate the mail triage plugin by Microsoft device code."""

from mailbox_graph import MailboxError, login


if __name__ == "__main__":
    try:
        result = login()
        print(f"Authenticated {result['mailbox']}; cache saved to {result['cache']}")
    except MailboxError as exc:
        raise SystemExit(f"Authentication failed: {exc}")
