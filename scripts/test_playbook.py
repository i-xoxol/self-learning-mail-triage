import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from playbook_store import PlaybookStore


class PlaybookTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = PlaybookStore(Path(self.tempdir.name) / "playbook.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def _matched_event(self, number):
        event = self.store.record_draft(
            draft_id=f"draft-{number}", original_message_id=f"in-{number}",
            conversation_id=f"c-{number}", subject="Re: Example", to=[], cc=[],
            proposed_body="Longer draft", rules=[],
        )
        self.store.match_draft(event["id"], {"id": f"sent-{number}", "body": "Short draft", "cc": []}, {"body_changed": True})
        return event["id"]

    def test_new_playbook_has_no_personal_rules(self):
        rules = self.store.relevant_rules("registration waiver", 8)
        self.assertEqual(rules, [])
        self.assertEqual(self.store.contacts(), [])

    def test_operational_proposal_requires_review(self):
        proposal = self.store.create_proposal({
            "title": "Route a process", "topic": "routing", "rule_type": "routing",
            "risk_level": "medium", "rationale": "One correction", "evidence_event_ids": [],
            "question": "Adopt this routing rule?",
            "rule": {"title": "Route a process", "topic": "routing", "triggers": ["process"], "guidance": "Ask the office."},
        })
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(len(self.store.optional_questions()), 1)

    @patch.dict("os.environ", {"OUTLOOK_AUTO_LEARN_STYLE": "1"})
    def test_repeated_low_risk_style_can_auto_activate(self):
        evidence = [self._matched_event(i) for i in range(3)]
        proposal = self.store.create_proposal({
            "title": "Prefer shorter confirmations", "topic": "brevity", "rule_type": "style",
            "risk_level": "low", "rationale": "Repeated shortening", "evidence_event_ids": evidence,
            "rule": {"title": "Prefer shorter confirmations", "topic": "brevity", "triggers": ["confirmation"], "guidance": "Keep confirmations short."},
        })
        self.assertEqual(proposal["status"], "auto_approved")
        self.assertTrue(any(rule["title"] == "Prefer shorter confirmations" for rule in self.store.list_rules()))


if __name__ == "__main__":
    unittest.main()
