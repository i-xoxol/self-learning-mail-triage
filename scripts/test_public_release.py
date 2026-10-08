"""Offline checks for reusable configuration, learning gates, and auth isolation."""

import asyncio
import os
import tempfile
import subprocess
import sys
import importlib.util
import httpx
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull

from configure_mcp import configuration
from demo import run_demo
from mailbox_graph import Graph, MailboxError, _app_and_cache
from oauth_provider import PairingOAuthProvider
from playbook_store import PlaybookStore
from runtime_profile import email_voice, with_signature


class PublicReleaseTests(unittest.TestCase):
    def test_remote_http_requires_authentication_for_mcp(self):
        async def exercise():
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'OUTLOOK_MCP_PUBLIC_BASE_URL': 'https://mail-triage.example.com',
                'OUTLOOK_MCP_OAUTH_DB': str(Path(directory) / 'oauth.sqlite3'),
            }):
                spec = importlib.util.spec_from_file_location('http_boundary_server', Path(__file__).with_name('mcp_server.py'))
                server = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(server)
                app = server.mcp.streamable_http_app()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://mail-triage.example.com') as client:
                    self.assertEqual((await client.get('/healthz')).status_code, 200)
                    request = await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
                    self.assertEqual(request.status_code, 401)
                self.assertTrue(server._auth_settings.validate_token_resource)
        asyncio.run(exercise())

    def test_http_refuses_to_start_without_oauth_base_url(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('OUTLOOK_')}
        environment['OUTLOOK_MCP_TRANSPORT'] = 'streamable-http'
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('mcp_server.py'))],
                                env=environment, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HTTP requires', result.stderr)

    def test_missing_client_id_fails_before_network_access(self):
        with patch.dict(os.environ, {'OUTLOOK_GRAPH_CLIENT_ID': ''}), patch('mailbox_graph.msal.PublicClientApplication') as app:
            with self.assertRaises(MailboxError):
                _app_and_cache()
            app.assert_not_called()

    def test_graph_never_sends_credentials_to_other_hosts_or_tenants(self):
        client = Graph('fictional-token')
        with patch.object(client.session, 'request') as request:
            for path in ['https://example.com/v1.0/me/messages', '/users/example/messages',
                         'https://graph.microsoft.com.evil.example/v1.0/me/messages']:
                with self.assertRaises(MailboxError):
                    client.request('GET', path)
            request.assert_not_called()

    def test_profile_is_optional_and_signature_is_not_invented(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OUTLOOK_PROFILE_FILE': str(Path(directory) / 'missing.toml')}):
            self.assertEqual(email_voice()['source'], 'generic defaults; no mailbox analysis')
            self.assertEqual(with_signature('Hello.'), 'Hello.')

    def test_configured_signature_is_added_once_and_escapes_regex_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.toml'
            path.write_text('[signature]\ntext = "Best regards,\\nMorgan Lee"\nclosing_names = ["Morgan"]\n', encoding='utf-8')
            with patch.dict(os.environ, {'OUTLOOK_PROFILE_FILE': str(path)}):
                signed = with_signature('Hello.\n\nBest,\nMorgan')
                self.assertEqual(signed, 'Hello.\n\nBest regards,\nMorgan Lee')
                self.assertEqual(with_signature(signed), signed)

    def test_learning_demo_needs_no_mailbox_and_exposes_redacted_evidence(self):
        result = run_demo()
        self.assertFalse(result['email_account_connected'])
        self.assertEqual(result['proposal_before_demo_review'], 'pending')
        self.assertIn('<EMAIL>', result['retrieved_example'])
        self.assertEqual(run_demo(True)['proposal_before_demo_review'], 'auto_approved')

    def test_local_connection_requires_own_application_and_prompts_for_writes(self):
        with self.assertRaises(ValueError):
            configuration(Path('.'), 'python')
        entry = configuration(Path('.'), 'python', 'fictional-client')['mcpServers']['mail_triage']
        self.assertTrue(Path(entry['args'][0]).is_absolute())
        self.assertEqual(entry['tools']['create_reply_draft']['approval_mode'], 'prompt')

    def test_remote_connection_requires_https_and_no_embedded_credentials(self):
        for url in ['http://example.com/mcp', 'https://name:secret@example.com/mcp', 'https://example.com/mcp?token=secret']:
            with self.assertRaises(ValueError):
                configuration(Path('.'), 'python', remote_url=url)

    def test_style_auto_learning_does_not_activate_routing(self):
        with tempfile.TemporaryDirectory() as directory, PlaybookStore(Path(directory) / 'test.sqlite3') as store:
            evidence = []
            for number in range(3):
                event = store.record_draft(draft_id=str(number), original_message_id=str(number),
                    conversation_id=str(number), subject='Project', to=[], cc=[], proposed_body='Draft', rules=[])
                store.match_draft(event['id'], {'id': f'sent-{number}', 'body': 'Edited', 'cc': []}, {})
                evidence.append(event['id'])
            with patch.dict(os.environ, {'OUTLOOK_AUTO_LEARN_STYLE': '1'}):
                proposal = store.create_proposal({
                    'title': 'Route to support', 'topic': 'support', 'rule_type': 'routing', 'risk_level': 'low',
                    'rationale': 'Three edits', 'evidence_event_ids': evidence,
                    'rule': {'title': 'Route to support', 'topic': 'support', 'triggers': ['support'], 'guidance': 'Ask support.'},
                })
            self.assertEqual(proposal['status'], 'pending')
            self.assertEqual(store.list_rules(), [])

    def test_refresh_tokens_keep_the_resource_and_are_bound_to_the_client(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = PairingOAuthProvider(Path(directory) / 'oauth.sqlite3', 'https://mail.example.com')
            with self.assertRaises(TokenError):
                provider._issue_tokens('owner', ['mailbox'], 'https://other.example.com/mcp')
            owner = OAuthClientInformationFull(client_id='owner', redirect_uris=['https://example.com/callback'])
            other = OAuthClientInformationFull(client_id='other', redirect_uris=['https://example.com/callback'])
            issued = provider._issue_tokens('owner', ['mailbox'], 'https://mail.example.com/mcp')
            token = asyncio.run(provider.load_refresh_token(owner, issued.refresh_token))
            self.assertIsNone(asyncio.run(provider.load_refresh_token(other, issued.refresh_token)))
            with self.assertRaises(TokenError):
                asyncio.run(provider.exchange_refresh_token(other, token, ['mailbox']))
            with self.assertRaises(TokenError):
                asyncio.run(provider.exchange_refresh_token(owner, token, ['admin']))
            refreshed = asyncio.run(provider.exchange_refresh_token(owner, token, ['mailbox']))
            access = asyncio.run(provider.load_access_token(refreshed.access_token))
            self.assertEqual(access.resource, 'https://mail.example.com/mcp')
            self.assertIsNone(asyncio.run(provider.load_refresh_token(owner, issued.refresh_token)))
