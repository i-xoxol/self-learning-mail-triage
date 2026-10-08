from __future__ import annotations

import asyncio
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from oauth_provider import PairingOAuthProvider


def run(coro):
    return asyncio.run(coro)


def client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="chatgpt-test",
        client_secret="secret",
        redirect_uris=["https://chatgpt.com/callback"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="mailbox",
        client_name="ChatGPT test",
    )


def exercise_pairing_code_is_single_use_and_tokens_rotate():
    with tempfile.TemporaryDirectory() as temp:
        provider = PairingOAuthProvider(Path(temp) / "oauth.sqlite3", "https://mail-triage.example")
        oauth_client = client()
        run(provider.register_client(oauth_client))

        verifier = "correct horse battery staple"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params = AuthorizationParams(
            state="state-1",
            scopes=["mailbox"],
            code_challenge=challenge,
            redirect_uri="https://chatgpt.com/callback",
            redirect_uri_provided_explicitly=True,
            resource="https://mail-triage.example/mcp",
        )
        approval_url = run(provider.authorize(oauth_client, params))
        request_key = approval_url.split("request=", 1)[1]
        pairing_code = provider.create_pairing_code()
        callback = provider.approve(request_key, pairing_code)
        assert callback.startswith("https://chatgpt.com/callback?")
        authorization_code = callback.split("code=", 1)[1].split("&", 1)[0]
        loaded_code = run(provider.load_authorization_code(oauth_client, authorization_code))
        assert loaded_code is not None

        issued = run(provider.exchange_authorization_code(oauth_client, loaded_code))
        assert run(provider.load_access_token(issued.access_token)) is not None
        old_refresh = run(provider.load_refresh_token(oauth_client, issued.refresh_token))
        assert old_refresh is not None
        refreshed = run(provider.exchange_refresh_token(oauth_client, old_refresh, ["mailbox"]))
        assert refreshed.refresh_token != issued.refresh_token
        assert run(provider.load_refresh_token(oauth_client, issued.refresh_token)) is None

        second_url = run(provider.authorize(oauth_client, params))
        second_request = second_url.split("request=", 1)[1]
        try:
            provider.approve(second_request, pairing_code)
        except ValueError as exc:
            assert "already used" in str(exc)
        else:
            raise AssertionError("pairing code was accepted twice")


def exercise_expired_or_unknown_approval_is_rejected():
    with tempfile.TemporaryDirectory() as temp:
        provider = PairingOAuthProvider(Path(temp) / "oauth.sqlite3", "https://mail-triage.example")
        try:
            provider.approve("missing", "NOPE")
        except ValueError as exc:
            assert "expired" in str(exc)
        else:
            raise AssertionError("unknown approval request was accepted")


class PairingOAuthProviderTests(unittest.TestCase):
    def test_pairing_code_is_single_use_and_tokens_rotate(self):
        exercise_pairing_code_is_single_use_and_tokens_rotate()

    def test_expired_or_unknown_approval_is_rejected(self):
        exercise_expired_or_unknown_approval_is_rejected()
