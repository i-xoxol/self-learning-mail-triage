import tempfile
import unittest
from pathlib import Path

from draft_observer import observe
from playbook_store import PlaybookStore


class FakeSent:
    def recent_sent(self, maximum, since=None):
        return [{
            "id": "sent-1", "conversationId": "conversation-1", "subject": "RE: Registration",
            "sentDateTime": "2099-01-01T12:00:00Z",
            "body": {"content": "Hi Alex,\n\nPlease contact the Registrar.\n\nBest regards,\nMorgan Lee"},
            "toRecipients": [], "ccRecipients": [],
        }]


class ObserverTests(unittest.TestCase):
    def test_matches_and_compares_authored_text_without_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            with PlaybookStore(Path(directory) / "playbook.sqlite3") as store:
                store.record_draft(
                    draft_id="draft-1", original_message_id="in-1", conversation_id="conversation-1",
                    subject="Registration", to=["alex@example.edu"], cc=[],
                    proposed_body="Hi Alex,\n\nPlease contact the Registrar.\n\nBest regards,\nMorgan Lee\nAssistant Professor",
                    rules=["registration-registrar"],
                )
                result = observe(FakeSent(), store)
                outcome = store.matched_outcomes()[0]["outcome"]
        self.assertEqual(result["matched"], 1)
        self.assertFalse(outcome["body_changed"])
        self.assertEqual(outcome["similarity"], 1.0)


if __name__ == "__main__":
    unittest.main()
