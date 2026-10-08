"""Deterministic, privacy-minimized historical case-memory backfill."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from mailbox_graph import compact_sent_message
from playbook_store import PlaybookStore


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _plain_body(message: dict[str, Any], limit: int = 4000) -> str:
    body = str((message.get("body") or {}).get("content") or "")
    return body.replace("\r\n", "\n").replace("\r", "\n")[:limit]


def pair_historical_messages(
    sent_messages: list[dict[str, Any]],
    mailbox_messages: list[dict[str, Any]],
    mailbox: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pair authored Sent Items with the closest earlier inbound message."""
    normalized_mailbox = mailbox.strip().casefold()
    inbound_by_conversation: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    skipped_owner_or_draft = 0
    for message in mailbox_messages:
        conversation = str(message.get("conversationId") or "").strip()
        received = _timestamp(message.get("receivedDateTime"))
        sender = str(
            (((message.get("from") or {}).get("emailAddress") or {}).get("address") or "")
        ).strip().casefold()
        if not conversation or received is None or message.get("isDraft"):
            skipped_owner_or_draft += 1
            continue
        if sender and sender == normalized_mailbox:
            skipped_owner_or_draft += 1
            continue
        body = _plain_body(message)
        if not body.strip() and not str(message.get("subject") or "").strip():
            continue
        inbound_by_conversation[conversation].append((received, message))
    for messages in inbound_by_conversation.values():
        messages.sort(key=lambda item: item[0])

    pairs: list[dict[str, Any]] = []
    skipped_automated_or_empty = 0
    skipped_no_prior_inbound = 0
    for sent in sent_messages:
        compact = compact_sent_message(sent, 4000)
        sent_at = _timestamp(sent.get("sentDateTime"))
        conversation = str(sent.get("conversationId") or "").strip()
        if compact["automated"] or not compact["authored_text"] or sent_at is None or not conversation:
            skipped_automated_or_empty += 1
            continue
        candidates = [
            item for item in inbound_by_conversation.get(conversation, []) if item[0] <= sent_at
        ]
        if not candidates:
            skipped_no_prior_inbound += 1
            continue
        received_at, inbound = candidates[-1]
        inbound_text = "\n".join(
            part for part in (str(inbound.get("subject") or "").strip(), _plain_body(inbound)) if part
        )
        pairs.append(
            {
                "sent_message_id": str(sent.get("id") or ""),
                "inbound_message_id": str(inbound.get("id") or ""),
                "conversation_id": conversation,
                "subject": str(inbound.get("subject") or sent.get("subject") or "(no subject)"),
                "inbound_text": inbound_text,
                "final_response": compact["authored_text"],
                "received_at": received_at.replace(microsecond=0).isoformat(),
                "sent_at": sent_at.replace(microsecond=0).isoformat(),
            }
        )
    return pairs, {
        "skipped_owner_or_draft": skipped_owner_or_draft,
        "skipped_automated_or_empty": skipped_automated_or_empty,
        "skipped_no_prior_inbound": skipped_no_prior_inbound,
    }


def backfill_historical_cases(
    client: Any,
    mailbox: str,
    store: PlaybookStore,
    *,
    days: int = 365,
    max_sent: int = 10_000,
    max_mailbox_messages: int = 30_000,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch, pair, redact, and idempotently store historical reply cases."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = (reference - timedelta(days=days)).replace(microsecond=0).isoformat()
    sent = client.recent_sent(max_sent, since=since)
    mailbox_messages = client.historical_messages(max_mailbox_messages, since)
    pairs, skipped = pair_historical_messages(sent, mailbox_messages, mailbox)
    created = duplicate = excluded = 0
    for pair in pairs:
        result = store.upsert_historical_case(mailbox=mailbox, **pair)
        created += int(result["status"] == "created")
        duplicate += int(result["status"] == "duplicate")
        excluded += int(result["status"] == "excluded")
    redactions_refreshed = store.refresh_case_redaction(mailbox)
    pruned = store.prune_case_memory()
    return {
        "mailbox": mailbox.strip().casefold(),
        "window_days": days,
        "since": since,
        "sent_fetched": len(sent),
        "mailbox_messages_fetched": len(mailbox_messages),
        "candidate_pairs": len(pairs),
        "created": created,
        "duplicates": duplicate,
        "excluded": excluded,
        "pruned_now": pruned,
        "redactions_refreshed": redactions_refreshed,
        "sent_limit_reached": len(sent) >= max_sent,
        "mailbox_limit_reached": len(mailbox_messages) >= max_mailbox_messages,
        **skipped,
    }
