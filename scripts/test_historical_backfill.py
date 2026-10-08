import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from historical_backfill import backfill_historical_cases, pair_historical_messages
from playbook_store import PlaybookStore


def sent(message_id, conversation, when, body="Hi Alex,\n\nPlease contact the Registrar.\n\nBest,\nMorgan"):
    return {
        "id": message_id,
        "conversationId": conversation,
        "subject": "Re: CY-424 registration",
        "sentDateTime": when,
        "body": {"content": body},
        "toRecipients": [],
        "ccRecipients": [],
    }


def inbound(message_id, conversation, when, body="Can you approve registration for CY-424?"):
    return {
        "id": message_id,
        "conversationId": conversation,
        "subject": "CY-424 registration",
        "receivedDateTime": when,
        "from": {"emailAddress": {"address": "student@example.edu"}},
        "body": {"content": body},
        "isDraft": False,
    }


class HistoricalBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = PlaybookStore(Path(self.tempdir.name) / "playbook.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_pairing_selects_closest_prior_inbound(self):
        sent_items = [sent("sent-1", "conversation-1", "2026-09-10T12:00:00Z")]
        messages = [
            inbound("old", "conversation-1", "2026-09-08T10:00:00Z", "Old question"),
            inbound("closest", "conversation-1", "2026-09-10T11:00:00Z", "Current question"),
            inbound("later", "conversation-1", "2026-09-10T13:00:00Z", "Later question"),
        ]
        pairs, counts = pair_historical_messages(sent_items, messages, "owner@example.com")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["inbound_message_id"], "closest")
        self.assertIn("Current question", pairs[0]["inbound_text"])
        self.assertEqual(counts["skipped_no_prior_inbound"], 0)

    def test_pairing_skips_owner_mail_and_automated_responses(self):
        owner = inbound("owner", "conversation-1", "2026-09-10T10:00:00Z")
        owner["from"]["emailAddress"]["address"] = "OWNER@example.com"
        automated = sent("sent-1", "conversation-1", "2026-09-10T12:00:00Z")
        automated["subject"] = "Accepted: Meeting"
        pairs, counts = pair_historical_messages([automated], [owner], "owner@example.com")
        self.assertEqual(pairs, [])
        self.assertEqual(counts["skipped_owner_or_draft"], 1)
        self.assertEqual(counts["skipped_automated_or_empty"], 1)

    def test_store_is_redacted_and_idempotent(self):
        pair = {
            "mailbox": "OWNER@example.com",
            "sent_message_id": "sent-redacted",
            "inbound_message_id": "in-redacted",
            "conversation_id": "conversation-redacted",
            "subject": "CY-424 registration",
            "inbound_text": "Email student@example.edu or call 203-555-1212.\n\nBest,\nStudent Name",
            "final_response": "Use https://example.edu/form and contact registrar@example.edu.\n\nBest,\nMorgan",
            "received_at": "2026-09-10T10:00:00+00:00",
            "sent_at": "2026-09-10T11:00:00+00:00",
        }
        first = self.store.upsert_historical_case(**pair)
        second = self.store.upsert_historical_case(**pair)
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "duplicate")
        row = self.store.connection.execute("SELECT * FROM email_cases").fetchone()
        self.assertEqual(row["mailbox"], "owner@example.com")
        self.assertNotIn("student@example.edu", row["inbound_excerpt"])
        self.assertNotIn("Student Name", row["inbound_excerpt"])
        self.assertNotIn("https://", row["final_response_excerpt"])
        self.assertNotIn("Morgan", row["final_response_excerpt"])
        self.assertEqual(row["course"], "CY-424")

    def test_backfill_reports_limits_and_duplicates(self):
        class FakeGraph:
            def recent_sent(self, maximum, since=None):
                return [sent("sent-1", "conversation-1", "2026-09-10T12:00:00Z")]

            def historical_messages(self, maximum, since):
                return [inbound("in-1", "conversation-1", "2026-09-10T11:00:00Z")]

        kwargs = {
            "days": 365,
            "max_sent": 10,
            "max_mailbox_messages": 10,
            "now": datetime(2026, 9, 12, tzinfo=timezone.utc),
        }
        first = backfill_historical_cases(FakeGraph(), "owner@example.com", self.store, **kwargs)
        second = backfill_historical_cases(FakeGraph(), "owner@example.com", self.store, **kwargs)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["duplicates"], 1)
        self.assertFalse(first["sent_limit_reached"])
        self.assertEqual(first["since"], "2025-09-12T00:00:00+00:00")

    def test_refresh_removes_flattened_owner_signoff(self):
        pair = {
            "mailbox": "owner@example.com",
            "sent_message_id": "sent-inline-signoff",
            "inbound_message_id": "in-inline-signoff",
            "conversation_id": "conversation-inline-signoff",
            "subject": "Research collaboration",
            "inbound_text": "Would you like to collaborate?",
            "final_response": "Yes, I would be happy to collaborate. Best, Morgan",
            "received_at": "2026-09-10T10:00:00+00:00",
            "sent_at": "2026-09-10T11:00:00+00:00",
        }
        self.store.upsert_historical_case(**pair)
        row = self.store.connection.execute("SELECT final_response_excerpt FROM email_cases").fetchone()
        self.assertEqual(row[0], "Yes, I would be happy to collaborate.")
        self.assertEqual(self.store.refresh_case_redaction("owner@example.com"), 0)


if __name__ == "__main__":
    unittest.main()
