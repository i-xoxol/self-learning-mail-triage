"""Generate a machine-local MCP connection; never change a host's global config."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

PROMPT_TOOLS = [
    'apply_triage_plan', 'create_reply_draft', 'remember_email_rule',
    'upsert_verified_contact', 'review_rule_update', 'record_learning_feedback',
    'propose_rule_from_cases', 'propose_rule_update', 'observe_draft_outcomes',
]


def configuration(root: Path, executable: str, client_id: str = '', remote_url: str = '') -> dict:
    if remote_url:
        url = urlparse(remote_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use an HTTPS MCP URL without credentials, query, or fragment.')
        server = {'type': 'http', 'url': remote_url}
    else:
        if not client_id.strip():
            raise ValueError('Supply your own Entra application ID using --client-id.')
        server = {
            'command': executable,
            'args': [str((root / 'scripts' / 'mcp_server.py').resolve())],
            'env': {'OUTLOOK_GRAPH_CLIENT_ID': client_id.strip(), 'OUTLOOK_MCP_TRANSPORT': 'stdio'},
        }
    server.update({
        'enabled': True,
        'default_tools_approval_mode': 'prompt',
        'tools': {name: {'approval_mode': 'prompt'} for name in PROMPT_TOOLS},
        'startup_timeout_sec': 30,
        'tool_timeout_sec': 120,
    })
    return {'mcpServers': {'mail_triage': server}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-id', default=os.getenv('OUTLOOK_GRAPH_CLIENT_ID', ''))
    parser.add_argument('--remote-url', default='')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        config = configuration(root, sys.executable, args.client_id, args.remote_url)
    except ValueError as exc:
        parser.error(str(exc))
    destination = root / '.mcp.local.json'
    destination.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    print(f'Created {destination.name}. It is ignored by Git and contains machine-local paths.')
    print('Register this local marketplace, or copy the mail_triage server entry into your MCP client configuration.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
