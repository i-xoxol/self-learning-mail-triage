"""Match plugin-created drafts to later Sent Items without sending mail."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from mailbox_graph import compact_sent_message
from playbook_store import PlaybookStore


def _subject(value: str) -> str:
    return re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "", value.strip(), flags=re.I).casefold()


def _addresses(recipients: list[dict[str, Any]]) -> list[str]:
    return sorted(
        ((item.get("emailAddress") or {}).get("address") or "").casefold()
        for item in recipients
        if (item.get("emailAddress") or {}).get("address")
    )


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _maintain_case_memory(store: PlaybookStore) -> dict[str, Any]:
    """Keep optional case memory from breaking the existing draft-outcome observer."""
    try:
        return {
            "sync": store.sync_case_memory_from_matched(),
            "pruned": store.prune_case_memory(),
        }
    except Exception as exc:
        return {"error": f"case-memory maintenance failed: {type(exc).__name__}"}


def observe(client: Any, store: PlaybookStore, maximum_sent: int = 250) -> dict[str, Any]:
    pending = store.pending_drafts(limit=250)
    if not pending:
        return {
            "pending_checked": 0,
            "matched": 0,
            "expired": store.expire_old_drafts(),
            "pruned": store.prune_observation_text(),
            "case_memory": _maintain_case_memory(store),
            "matches": [],
        }
    earliest = min(item["created_at"] for item in pending)
    since = (datetime.fromisoformat(earliest) - timedelta(minutes=5)).astimezone(timezone.utc).isoformat()
    sent = client.recent_sent(maximum_sent, since=since)
    used: set[str] = set()
    matches: list[dict[str, Any]] = []
    for event in pending:
        candidates: list[tuple[int, dict[str, Any]]] = []
        for item in sent:
            if str(item.get("id")) in used:
                continue
            sent_at = str(item.get("sentDateTime") or "")
            if sent_at and _moment(sent_at) < _moment(event["created_at"]):
                continue
            score = 0
            if event.get("conversation_id") and item.get("conversationId") == event["conversation_id"]:
                score += 10
            if _subject(str(item.get("subject") or "")) == _subject(event["subject"]):
                score += 4
            if score >= 10:
                candidates.append((score, item))
        if not candidates:
            continue
        candidates.sort(key=lambda pair: (pair[0], pair[1].get("sentDateTime") or ""), reverse=True)
        raw = candidates[0][1]
        used.add(str(raw["id"]))
        compact = compact_sent_message(raw, 20000)
        proposed = compact_sent_message(
            {"body": {"content": event["proposed_body"]}, "subject": event["subject"]}, 20000
        )["authored_text"].strip()
        actual = compact["authored_text"].strip()
        proposed_cc = sorted(str(value).casefold() for value in event.get("cc", []))
        actual_cc = _addresses(raw.get("ccRecipients") or [])
        outcome = {
            "similarity": round(SequenceMatcher(None, proposed, actual).ratio(), 4),
            "body_changed": proposed != actual,
            "length_delta": len(actual) - len(proposed),
            "cc_changed": proposed_cc != actual_cc,
            "proposed_cc": proposed_cc,
            "sent_cc": actual_cc,
        }
        store.match_draft(
            event["id"],
            {"id": raw["id"], "body": actual, "cc": actual_cc},
            outcome,
        )
        matches.append({"event_id": event["id"], "sent_message_id": raw["id"], **outcome})
    return {
        "pending_checked": len(pending),
        "matched": len(matches),
        "expired": store.expire_old_drafts(),
        "pruned": store.prune_observation_text(),
        "case_memory": _maintain_case_memory(store),
        "matches": matches,
    }
