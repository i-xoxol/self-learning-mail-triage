"""Read-only helper to verify a known contact from recent correspondence."""

import argparse

from mailbox_graph import graph


parser = argparse.ArgumentParser()
parser.add_argument("query")
args = parser.parse_args()
client, _ = graph()
query = args.query.casefold()
matches = set()
for message in client.recent_sent(500):
    for item in (message.get("toRecipients") or []) + (message.get("ccRecipients") or []):
        contact = item.get("emailAddress") or {}
        name, address = str(contact.get("name") or ""), str(contact.get("address") or "")
        if query in f"{name} {address}".casefold():
            matches.add((name, address.casefold()))
for match in sorted(matches):
    print("\t".join(match))
