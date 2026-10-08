"""Local administration for verified contacts and sanitized playbook exports."""

import argparse
import json

from playbook_store import PlaybookStore


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(dest="command", required=True)
contact = subparsers.add_parser("verify-contact")
contact.add_argument("--name", required=True)
contact.add_argument("--role", required=True)
contact.add_argument("--email", required=True)
contact.add_argument("--cc-policy", required=True)
subparsers.add_parser("export")
args = parser.parse_args()

with PlaybookStore() as store:
    if args.command == "verify-contact":
        result = store.upsert_contact(args.name, args.role, args.email, args.cc_policy)
    else:
        result = store.export_sanitized()
print(json.dumps(result, indent=2, ensure_ascii=False))
