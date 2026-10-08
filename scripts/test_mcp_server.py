import importlib.util
import sys
import time
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("triage_mcp_server", SCRIPT_DIR / "mcp_server.py")
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)
from mailbox_graph import reply_text_to_html


class FakeGraph:
    def __init__(self):
        self.calls = []

    def folder(self, name):
        return {"id": f"{name}-id", "unreadItemCount": 2}

    def message(self, message_id):
        return {
            "id": message_id,
            "internetMessageId": f"internet-{message_id}",
            "parentFolderId": "inbox-id",
            "subject": f"Subject {message_id}",
            "conversationId": "conversation-1",
            "from": {"emailAddress": {"name": "Alex", "address": "alex@example.edu"}},
            "isRead": False,
        }

    def unread_inbox(self, maximum):
        return [
            {
                "id": "1", "internetMessageId": "internet-1", "parentFolderId": "inbox-id",
                "conversationId": "conversation-1", "subject": "Subject 1",
                "from": {"emailAddress": {"name": "Alex", "address": "alex@example.edu"}},
                "receivedDateTime": "2026-09-03T10:00:00Z", "bodyPreview": "Please help.",
                "isRead": False, "hasAttachments": False, "importance": "normal",
            }
        ][:maximum]

    def mark_read(self, message_id):
        self.calls.append(("read", message_id))

    def move_to_archive(self, message_id, archive_id):
        self.calls.append(("archive", message_id, archive_id))
        return {"id": f"moved-{message_id}"}

    def recent_sent(self, maximum):
        return [
            {
                "id": "sent-1",
                "subject": "Re: Meeting",
                "sentDateTime": "2026-09-01T12:00:00Z",
                "toRecipients": [{"emailAddress": {"address": "student@example.edu"}}],
                "ccRecipients": [],
                "body": {"content": "Hi Alex,\n\nThat is fine.\n\nBest,\nMorgan\n\nFrom: Alex\nQuoted text"},
            }
        ][:maximum]

    def create_reply_draft(self, message_id, reply_text, cc=None):
        self.calls.append(("draft", message_id, reply_text, cc or []))
        return {"id": "draft-1", "subject": "RE: Subject 1", "isDraft": True}


class TriageServerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("OUTLOOK_PLAYBOOK_DB")
        os.environ["OUTLOOK_PLAYBOOK_DB"] = str(Path(self.tempdir.name) / "playbook.sqlite3")
        server.SNAPSHOTS.clear()
        server.SNAPSHOTS["snapshot"] = {
            "created_epoch": time.time(),
            "mailbox": "owner@example.com",
            "inbox_id": "inbox-id",
            "messages": {
                "1": {
                    "id": "1",
                    "subject": "Subject 1",
                    "internet_message_id": "internet-1",
                    "sender": {"name": "Alex", "address": "alex@example.edu"},
                    "conversation_id": "conversation-1",
                },
                "2": {
                    "id": "2",
                    "subject": "Subject 2",
                    "internet_message_id": "internet-2",
                    "sender": {"name": "Taylor", "address": "taylor@example.edu"},
                },
            },
        }

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("OUTLOOK_PLAYBOOK_DB", None)
        else:
            os.environ["OUTLOOK_PLAYBOOK_DB"] = self.old_db
        self.tempdir.cleanup()

    def plan(self):
        return [
            {"id": "1", "action": "archive_read", "importance": "low", "summary": "Promo", "reason": "No action"},
            {"id": "2", "action": "keep_unread", "importance": "high", "summary": "Request", "reason": "Reply needed"},
        ]

    def test_confirmation_is_required(self):
        with self.assertRaises(server.MailboxError):
            server.apply_triage_plan("snapshot", self.plan(), confirmed=False)

    def test_unread_inventory_returns_a_complete_snapshot(self):
        client = FakeGraph()
        with patch.object(server, "graph", return_value=(client, "owner@example.com")):
            result = server.list_unread_inbox()
        self.assertTrue(result["snapshot_id"])
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["messages"][0]["id"], "1")

    def test_complete_snapshot_is_required(self):
        with self.assertRaises(server.MailboxError):
            server.apply_triage_plan("snapshot", self.plan()[:1], confirmed=True)

    def test_expired_snapshot_is_rejected_without_mutation(self):
        server.SNAPSHOTS["snapshot"]["created_epoch"] = time.time() - server.SNAPSHOT_TTL_SECONDS - 1
        with patch.object(server, "graph") as graph:
            with self.assertRaises(server.MailboxError):
                server.apply_triage_plan("snapshot", self.plan(), confirmed=True)
            graph.assert_not_called()

    def test_mailbox_change_is_rejected_without_mutation(self):
        client = FakeGraph()
        with patch.object(server, "graph", return_value=(client, "other@example.com")):
            with self.assertRaises(server.MailboxError):
                server.apply_triage_plan("snapshot", self.plan(), confirmed=True)
        self.assertEqual(client.calls, [])

    def test_changed_message_identity_is_skipped(self):
        client = FakeGraph()
        current = client.message("1")
        current["internetMessageId"] = "a-different-message"
        with patch.object(server, "graph", return_value=(client, "owner@example.com")), \
             patch.object(client, "message", return_value=current):
            result = server.apply_triage_plan("snapshot", self.plan(), confirmed=True)
        self.assertEqual(client.calls, [])
        self.assertEqual(result["counts"]["skipped_or_partial"], 1)

    def test_archive_is_read_first_and_keep_is_untouched(self):
        client = FakeGraph()
        with patch.object(server, "graph", return_value=(client, "owner@example.com")):
            result = server.apply_triage_plan("snapshot", self.plan(), confirmed=True)
        self.assertEqual(client.calls, [("read", "1"), ("archive", "1", "archive-id")])
        self.assertEqual(result["counts"], {"archived_read": 1, "marked_read": 0, "untouched": 1, "skipped_or_partial": 0})

    def test_default_voice_is_generic_and_available(self):
        profile = server.get_email_voice()
        self.assertEqual(profile["profile_name"], "General email voice")
        self.assertIn("generic", profile["source"])
        self.assertTrue(profile["core"])

    def test_contact_reference_starts_empty(self):
        result = server.lookup_reference_contacts("project manager")
        self.assertEqual(result["count"], 0)
        self.assertIn("not automatic authority", result["routing_note"])

    def test_sent_samples_omit_recipients_and_quoted_history(self):
        client = FakeGraph()
        with patch.object(server, "graph", return_value=(client, "owner@example.com")):
            result = server.list_recent_sent_samples(max_messages=1, body_chars=500)
        sample = result["samples"][0]
        self.assertEqual(sample["authored_text"], "Hi Alex,\nThat is fine.\nBest,\nMorgan")
        self.assertNotIn("toRecipients", sample)
        self.assertNotIn("Quoted text", sample["authored_text"])

    def test_reply_draft_uses_configured_signature(self):
        client = FakeGraph()
        with patch.object(server, "graph", return_value=(client, "owner@example.com")), \
             patch.object(server, "_with_canonical_signature", side_effect=lambda value: value + "\n\nBest regards,\nMorgan Lee"):
            result = server.create_reply_draft(
                "snapshot", "1", "Hi Alex,\n\nThat is fine.", confirmed=True
            )
        self.assertEqual(client.calls[-1][2].count("Best regards,"), 1)
        self.assertTrue(result["draft"]["canonical_signature_added"])
        self.assertTrue(result["draft"]["observation_event_id"])

    def test_outlook_html_preserves_signature_lines_and_escapes_content(self):
        rendered = reply_text_to_html(
            "Hi Luke,\n\nThat is fine & confirmed.\n\nBest regards,\nMorgan Lee\n"
            "Assistant Professor of Cybersecurity,\nSchool of Computing and Engineering\n"
            "College of Arts and Sciences\n\nBook time to meet with me:\n"
            + "https://outlook.office.com/bookwithme/user/example"
        )
        self.assertIn("Hi Luke,</div><br><div>That is fine &amp; confirmed.", rendered)
        self.assertIn("Best regards,<br>Morgan Lee<br>Assistant Professor", rendered)
        self.assertIn("School of Computing and Engineering<br>College of Arts and Sciences", rendered)
        self.assertIn(f'<a href="{"https://outlook.office.com/bookwithme/user/example"}">Book time to meet with me</a>', rendered)

    def test_relevant_rules_and_verified_contact_gate(self):
        rules = server.get_relevant_email_rules("I cannot register for a closed course")
        self.assertEqual(rules["count"], 0)
        with self.assertRaises(server.MailboxError):
            server.create_reply_draft(
                "snapshot", "1", "Hi Alex,\n\nPlease contact the Registrar.",
                cc_contact_ids=["unknown"], confirmed=True,
            )


if __name__ == "__main__":
    unittest.main()
