"""Run a fictional learning loop in a temporary database, without email access."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from playbook_store import PlaybookStore


def run_demo(auto_style: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix='mail-triage-demo-') as directory:
        with PlaybookStore(Path(directory) / 'fictional.sqlite3') as store:
            evidence = []
            for number in range(3):
                event = store.record_draft(
                    draft_id=f'fictional-draft-{number}', original_message_id=f'fictional-in-{number}',
                    conversation_id=f'fictional-thread-{number}', mailbox='owner@example.com',
                    subject='Re: Meeting confirmation', to=['alex@example.com'], cc=[], rules=[],
                    inbound_excerpt='Could you confirm our meeting? Contact alex@example.com for context.',
                    proposed_body='Hi Alex, Thank you for reaching out. I am writing to confirm the meeting we discussed.',
                )
                store.match_draft(event['id'], {'id': f'fictional-sent-{number}', 'body': 'Confirmed. See you then.', 'cc': []},
                                  {'body_changed': True, 'length_delta': -60, 'cc_changed': False})
                evidence.append(event['id'])
            store.sync_case_memory_from_matched()
            with patch.dict(os.environ, {'OUTLOOK_AUTO_LEARN_STYLE': '1' if auto_style else '0'}):
                proposal = store.create_proposal({
                    'title': 'Short confirmations', 'topic': 'meeting', 'rule_type': 'style', 'risk_level': 'low',
                    'rationale': 'Three fictional replies were shortened by the owner.', 'evidence_event_ids': evidence,
                    'rule': {'title': 'Short confirmations', 'topic': 'meeting', 'triggers': ['meeting', 'confirmation'],
                             'guidance': 'Use one or two sentences for a simple confirmation.'},
                })
            before = proposal['status']
            if before == 'pending':
                store.review_proposal(proposal['id'], 'approve')  # Fictional owner approval only.
            cases = store.search_cases('owner@example.com', 'meeting confirmation', limit=1)
            return {
                'fictional_demo': True, 'email_account_connected': False,
                'matched_outcomes': len(evidence), 'proposal_before_demo_review': before,
                'active_rule': store.relevant_rules('meeting confirmation')[0]['guidance'],
                'retrieved_example': cases[0]['inbound_excerpt'],
                'storage': 'temporary database removed when the demo exits',
            }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auto-style', action='store_true', help='Demonstrate opt-in style activation using fictional evidence.')
    args = parser.parse_args()
    print(json.dumps(run_demo(args.auto_style), indent=2))
