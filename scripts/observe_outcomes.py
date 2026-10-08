"""Scheduled entry point for post-send draft observation."""

from mailbox_graph import graph
from draft_observer import observe
from playbook_store import PlaybookStore


if __name__ == "__main__":
    client, mailbox = graph()
    with PlaybookStore() as store:
        result = observe(client, store)
    print({"mailbox": mailbox, **result})
