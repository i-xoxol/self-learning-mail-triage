"""Constrained delegated Microsoft Graph client for Outlook triage."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from html import escape, unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import msal
import requests

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/organizations"
DEFAULT_CACHE = str(Path.home() / ".local" / "share" / "mail-triage" / "msal-cache.json")
SCOPES = ["Mail.ReadWrite"]


def reply_text_to_html(text: str) -> str:
    """Render a plain-text reply as safe Outlook HTML while preserving line breaks."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n{2,}", normalized):
        lines = paragraph.split("\n")
        if (
            len(lines) == 2
            and lines[0].strip().rstrip(":").casefold() == "book time to meet with me"
            and lines[1].strip().startswith("https://outlook.office.com/bookwithme/")
        ):
            booking_url = escape(lines[1].strip(), quote=True)
            paragraphs.append(f'<div><a href="{booking_url}">Book time to meet with me</a></div>')
            continue
        rendered_lines: list[str] = []
        for line in lines:
            safe_line = escape(line, quote=True)
            safe_line = re.sub(
                r"https://outlook\.office\.com/bookwithme/[^\s<]+",
                lambda match: (
                    f'<a href="{match.group(0)}">{match.group(0)}</a>'
                ),
                safe_line,
            )
            rendered_lines.append(safe_line)
        paragraphs.append("<div>" + "<br>".join(rendered_lines) + "</div>")
    return '<div style="font-family: Aptos, Calibri, Arial, sans-serif; font-size: 11pt;">' + "<br>".join(paragraphs) + "</div>"


class MailboxError(RuntimeError):
    pass


def settings() -> dict[str, str]:
    return {
        "cache": os.environ.get("OUTLOOK_MSAL_CACHE", DEFAULT_CACHE),
        "client_id": os.environ.get("OUTLOOK_GRAPH_CLIENT_ID", "").strip(),
        "authority": os.environ.get("OUTLOOK_GRAPH_AUTHORITY", DEFAULT_AUTHORITY),
    }


def _save_cache(cache: msal.SerializableTokenCache, path: Path) -> None:
    if not cache.has_state_changed:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(cache.serialize())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _app_and_cache() -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache, Path]:
    config = settings()
    if not config["client_id"]:
        raise MailboxError("Set OUTLOOK_GRAPH_CLIENT_ID to your own Entra public-client application ID. See docs/authentication.md.")
    cache_path = Path(config["cache"]).expanduser()
    cache = msal.SerializableTokenCache()
    if cache_path.is_file():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(config["client_id"], authority=config["authority"], token_cache=cache)
    return app, cache, cache_path


def login() -> dict[str, Any]:
    app, cache, cache_path = _app_and_cache()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise MailboxError(flow.get("error_description") or "Could not start device-code authentication")
    print(flow.get("message") or f"Open {flow['verification_uri']} and enter code {flow['user_code']}", flush=True)
    result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache, cache_path)
    if "access_token" not in result:
        raise MailboxError(result.get("error_description") or result.get("error") or "Device-code login failed")
    accounts = app.get_accounts()
    mailbox = next((str(item.get("username")) for item in accounts if item.get("username")), "unknown")
    return {"authenticated": True, "mailbox": mailbox, "cache": str(cache_path)}


def authentication_status(acquire: bool = True) -> dict[str, Any]:
    app, cache, cache_path = _app_and_cache()
    accounts = app.get_accounts()
    if not accounts:
        return {
            "authenticated": False,
            "reason": "No cached Microsoft account",
            "login_command": "python .\\scripts\\authenticate.py",
            "cache": str(cache_path),
        }
    usernames = [str(item.get("username") or item.get("home_account_id") or "unknown") for item in accounts]
    if not acquire:
        return {"authenticated": True, "accounts": usernames, "cache": str(cache_path)}
    if len(accounts) != 1:
        return {
            "authenticated": False,
            "reason": "The cache contains multiple accounts; use a dedicated cache for this plugin",
            "accounts": usernames,
            "cache": str(cache_path),
        }
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _save_cache(cache, cache_path)
    if not result or "access_token" not in result:
        return {
            "authenticated": False,
            "reason": (result or {}).get("error_description") or "Silent authentication unavailable",
            "mailbox": usernames[0],
            "login_command": "python .\\scripts\\authenticate.py",
            "cache": str(cache_path),
        }
    return {"authenticated": True, "mailbox": usernames[0], "cache": str(cache_path)}


def acquire_token() -> tuple[str, str]:
    app, cache, cache_path = _app_and_cache()
    accounts = app.get_accounts()
    if len(accounts) != 1:
        raise MailboxError("A cache containing exactly one Microsoft account is required. Run authenticate.py.")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _save_cache(cache, cache_path)
    if not result or "access_token" not in result:
        raise MailboxError("Authentication expired or unavailable. Run: python .\\scripts\\authenticate.py")
    mailbox = str(accounts[0].get("username") or accounts[0].get("home_account_id") or "unknown")
    return str(result["access_token"]), mailbox


class Graph:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("https://") else GRAPH_ROOT + path
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or not parsed.path.startswith("/v1.0/me/"):
            raise MailboxError("Only delegated /me paths on Microsoft Graph are allowed")
        response = None
        for attempt in range(5):
            response = self.session.request(method, url, timeout=30, allow_redirects=False, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt < 4:
                time.sleep(min(float(response.headers.get("Retry-After", 2**attempt)), 30.0))
        assert response is not None
        if not response.ok:
            raise MailboxError(f"Microsoft Graph request failed ({response.status_code}): {response.text[:800]}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def folder(self, name: str) -> dict[str, Any]:
        return self.request("GET", f"/me/mailFolders/{name}?$select=id,displayName,unreadItemCount")

    def unread_inbox(self, maximum: int) -> list[dict[str, Any]]:
        fields = "id,internetMessageId,parentFolderId,conversationId,subject,from,receivedDateTime,bodyPreview,isRead,hasAttachments,importance"
        url = (
            "/me/mailFolders/inbox/messages?$filter=isRead%20eq%20false"
            f"&$select={fields}&$orderby=receivedDateTime%20desc&$top=50"
        )
        messages: list[dict[str, Any]] = []
        while url and len(messages) < maximum:
            page = self.request("GET", url)
            messages.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
        return messages[:maximum]

    def recent_sent(self, maximum: int, since: str | None = None) -> list[dict[str, Any]]:
        fields = "id,conversationId,subject,sentDateTime,body,toRecipients,ccRecipients"
        filter_part = f"$filter=sentDateTime%20ge%20{quote(since, safe=':-.TZ')}&" if since else ""
        url = (
            "/me/mailFolders/sentitems/messages?"
            f"{filter_part}$select={fields}&$orderby=sentDateTime%20desc&$top=200"
        )
        messages: list[dict[str, Any]] = []
        while url and len(messages) < maximum:
            page = self.request(
                "GET",
                url,
                headers={"Prefer": 'outlook.body-content-type="text"'},
            )
            messages.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
        return messages[:maximum]

    def historical_messages(self, maximum: int, since: str) -> list[dict[str, Any]]:
        """Read mailbox messages received since a cutoff for local historical pairing."""
        fields = (
            "id,internetMessageId,parentFolderId,conversationId,subject,from,"
            "receivedDateTime,sentDateTime,body,isDraft"
        )
        encoded_since = quote(since, safe=":-.TZ")
        url = (
            "/me/messages?"
            f"$filter=receivedDateTime%20ge%20{encoded_since}"
            f"&$select={fields}&$orderby=receivedDateTime%20desc&$top=200"
        )
        messages: list[dict[str, Any]] = []
        while url and len(messages) < maximum:
            page = self.request(
                "GET",
                url,
                headers={"Prefer": 'outlook.body-content-type="text"'},
            )
            messages.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
        return messages[:maximum]

    def message(self, message_id: str) -> dict[str, Any]:
        fields = "id,internetMessageId,parentFolderId,conversationId,subject,isRead,from"
        return self.request("GET", f"/me/messages/{quote(message_id, safe='')}?$select={fields}")

    def mark_read(self, message_id: str) -> None:
        self.request(
            "PATCH",
            f"/me/messages/{quote(message_id, safe='')}",
            headers={"Content-Type": "application/json"},
            json={"isRead": True},
        )

    def move_to_archive(self, message_id: str, archive_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/me/messages/{quote(message_id, safe='')}/move",
            headers={"Content-Type": "application/json"},
            json={"destinationId": archive_id},
        )

    def create_reply_draft(self, message_id: str, comment: str, cc: list[dict[str, str]] | None = None) -> dict[str, Any]:
        draft = self.request(
            "POST",
            f"/me/messages/{quote(message_id, safe='')}/createReply",
            headers={"Content-Type": "application/json"},
            json={
                "message": {
                    "body": {
                        "contentType": "HTML",
                        "content": reply_text_to_html(comment),
                    }
                }
            },
        )
        if cc:
            recipients = [
                {"emailAddress": {"name": item.get("name") or item["address"], "address": item["address"]}}
                for item in cc
            ]
            updated = self.request(
                "PATCH",
                f"/me/messages/{quote(draft['id'], safe='')}",
                headers={"Content-Type": "application/json"},
                json={"ccRecipients": recipients},
            )
            if isinstance(updated, dict):
                draft.update(updated)
        return draft


def graph() -> tuple[Graph, str]:
    token, mailbox = acquire_token()
    return Graph(token), mailbox


def compact_message(message: dict[str, Any], preview_chars: int) -> dict[str, Any]:
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    return {
        "id": message["id"],
        "internet_message_id": message.get("internetMessageId"),
        "parent_folder_id": message.get("parentFolderId"),
        "conversation_id": message.get("conversationId"),
        "subject": message.get("subject") or "(no subject)",
        "sender": {"name": sender.get("name"), "address": sender.get("address")},
        "received": message.get("receivedDateTime"),
        "preview": (message.get("bodyPreview") or "")[:preview_chars],
        "has_attachments": bool(message.get("hasAttachments")),
        "importance": message.get("importance"),
    }


def compact_sent_message(message: dict[str, Any], body_chars: int) -> dict[str, Any]:
    """Keep the authored portion of sent mail without recipients or quoted history."""
    raw = str((message.get("body") or {}).get("content") or "")
    if "<" in raw and ">" in raw:
        raw = re.sub(r"(?is)<(br|/p|/div|/li|/tr)\b[^>]*>", "\n", raw)
        raw = re.sub(r"(?is)<[^>]+>", " ", raw)
        raw = unescape(raw)
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    quoted = re.search(
        r"(?im)^\s*(?:-{2,}\s*original message\s*-{2,}|from:|sent:|on .{1,160} wrote:)\s*",
        text,
    )
    if quoted:
        text = text[: quoted.start()]
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]

    # Retain the sign-off and name, but drop the institutional signature block.
    for index, line in enumerate(lines):
        if re.fullmatch(r"(?i)(best|best regards|kind regards|regards|sincerely)[,!]?", line):
            lines = lines[: min(index + 2, len(lines))]
            break
    authored = "\n".join(lines).strip()
    automated = (
        authored.startswith("This meeting was scheduled from the bookings page")
        or str(message.get("subject") or "").startswith(("Accepted:", "Declined:", "Tentative:"))
    )
    return {
        "id": message.get("id"),
        "conversation_id": message.get("conversationId"),
        "subject": message.get("subject") or "(no subject)",
        "sent": message.get("sentDateTime"),
        "to_count": len(message.get("toRecipients") or []),
        "cc_count": len(message.get("ccRecipients") or []),
        "cc": [
            ((item.get("emailAddress") or {}).get("address") or "").casefold()
            for item in (message.get("ccRecipients") or [])
            if (item.get("emailAddress") or {}).get("address")
        ],
        "authored_text": authored[:body_chars],
        "authored_text_truncated": len(authored) > body_chars,
        "automated": automated,
    }
