"""Durable, auditable behavioral memory for mail triage."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from case_memory import (
    DEFAULT_CASE_RETENTION_DAYS,
    EVIDENCE_NOTICE,
    REDACTION_VERSION,
    extract_case_metadata,
    normalize_case_excerpt,
    rank_cases,
)

DEFAULT_DB = Path.home() / ".local" / "share" / "mail-triage" / "playbook.sqlite3"
SCHEMA_VERSION = 2
ALLOWED_RULE_TYPES = {"style", "operational", "routing", "recipient", "safety"}
ALLOWED_PROPOSAL_DECISIONS = {"approve", "reject"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    return Path(os.environ.get("OUTLOOK_PLAYBOOK_DB", str(DEFAULT_DB))).expanduser()


def case_retention_days() -> int:
    try:
        value = int(os.environ.get("OUTLOOK_CASE_RETENTION_DAYS", DEFAULT_CASE_RETENTION_DAYS))
    except ValueError:
        value = DEFAULT_CASE_RETENTION_DAYS
    return min(max(value, 30), 3650)


def case_memory_enabled() -> bool:
    return os.environ.get("OUTLOOK_CASE_MEMORY_ENABLED", "1").strip().casefold() not in {
        "0", "false", "no", "off"
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class PlaybookError(RuntimeError):
    pass


class PlaybookStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or db_path()).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PlaybookStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                triggers_json TEXT NOT NULL,
                guidance TEXT NOT NULL,
                exceptions TEXT NOT NULL DEFAULT '',
                prohibited TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('active','inactive')),
                confidence REAL NOT NULL DEFAULT 1.0,
                source_type TEXT NOT NULL,
                source_ref TEXT,
                evidence_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS contacts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                cc_policy TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS draft_events (
                id TEXT PRIMARY KEY,
                draft_id TEXT NOT NULL UNIQUE,
                original_message_id TEXT NOT NULL,
                conversation_id TEXT,
                mailbox TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL,
                inbound_excerpt TEXT NOT NULL DEFAULT '',
                to_json TEXT NOT NULL,
                cc_json TEXT NOT NULL,
                proposed_body TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','matched','expired')),
                sent_message_id TEXT,
                sent_body TEXT,
                sent_cc_json TEXT,
                observed_at TEXT,
                outcome_json TEXT
            );
            CREATE TABLE IF NOT EXISTS learning_proposals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                rule_json TEXT NOT NULL,
                rationale TEXT NOT NULL,
                risk_level TEXT NOT NULL CHECK(risk_level IN ('low','medium','high')),
                evidence_event_ids_json TEXT NOT NULL,
                evidence_count INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','approved','auto_approved','rejected')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback_questions (
                id TEXT PRIMARY KEY,
                proposal_id TEXT,
                question TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','answered','dismissed')),
                answer TEXT,
                created_at TEXT NOT NULL,
                answered_at TEXT,
                FOREIGN KEY(proposal_id) REFERENCES learning_proposals(id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT,
                details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS email_cases (
                id TEXT PRIMARY KEY,
                source_event_id TEXT NOT NULL UNIQUE,
                mailbox TEXT NOT NULL,
                conversation_id TEXT,
                subject TEXT NOT NULL,
                inbound_excerpt TEXT NOT NULL,
                final_response_excerpt TEXT NOT NULL,
                topic TEXT NOT NULL,
                course TEXT NOT NULL,
                sender_role TEXT NOT NULL,
                injection_signals_json TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT NOT NULL,
                stale_after TEXT,
                eligible INTEGER NOT NULL DEFAULT 1 CHECK(eligible IN (0,1)),
                exclusion_reason TEXT NOT NULL DEFAULT '',
                redaction_version INTEGER NOT NULL,
                FOREIGN KEY(source_event_id) REFERENCES draft_events(id)
            );
            CREATE INDEX IF NOT EXISTS idx_email_cases_mailbox_eligible
              ON email_cases(mailbox,eligible,resolved_at);
            CREATE INDEX IF NOT EXISTS idx_email_cases_conversation
              ON email_cases(mailbox,conversation_id);
            """
        )
        draft_columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(draft_events)").fetchall()
        }
        if "mailbox" not in draft_columns:
            self.connection.execute("ALTER TABLE draft_events ADD COLUMN mailbox TEXT NOT NULL DEFAULT ''")
        if "inbound_excerpt" not in draft_columns:
            self.connection.execute("ALTER TABLE draft_events ADD COLUMN inbound_excerpt TEXT NOT NULL DEFAULT ''")
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    def _audit(self, event_type: str, object_type: str, object_id: str | None, details: Any) -> None:
        self.connection.execute(
            "INSERT INTO audit_log(occurred_at,event_type,object_type,object_id,details_json) VALUES(?,?,?,?,?)",
            (utc_now(), event_type, object_type, object_id, _json(details)),
        )

    @staticmethod
    def _rule(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["triggers"] = _loads(result.pop("triggers_json"), [])
        return result

    def relevant_rules(self, context: str, limit: int = 8) -> list[dict[str, Any]]:
        text = context.casefold()
        rows = self.connection.execute(
            "SELECT * FROM rules WHERE status='active' AND (expires_at IS NULL OR expires_at>?)",
            (utc_now(),),
        ).fetchall()
        ranked: list[tuple[int, float, dict[str, Any]]] = []
        for row in rows:
            rule = self._rule(row)
            score = sum(1 for term in rule["triggers"] if str(term).casefold() in text)
            if score:
                ranked.append((score, float(rule["confidence"]), rule))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]]

    def list_rules(self, status: str = "active") -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM rules WHERE status=? ORDER BY topic,title", (status,)
        ).fetchall()
        return [self._rule(row) for row in rows]

    def remember_rule(self, rule: dict[str, Any], source_ref: str | None = None) -> dict[str, Any]:
        if rule.get("rule_type") not in ALLOWED_RULE_TYPES:
            raise PlaybookError(f"Unsupported rule_type: {rule.get('rule_type')}")
        triggers = [str(item).strip() for item in rule.get("triggers", []) if str(item).strip()]
        if not triggers:
            raise PlaybookError("At least one trigger is required")
        now = utc_now()
        rule_id = str(rule.get("id") or uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO rules
            (id,title,topic,rule_type,triggers_json,guidance,exceptions,prohibited,status,
             confidence,source_type,source_ref,evidence_count,created_at,updated_at,expires_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title,topic=excluded.topic,
              rule_type=excluded.rule_type,triggers_json=excluded.triggers_json,guidance=excluded.guidance,
              exceptions=excluded.exceptions,prohibited=excluded.prohibited,status='active',
              confidence=excluded.confidence,source_type=excluded.source_type,source_ref=excluded.source_ref,
              evidence_count=excluded.evidence_count,updated_at=excluded.updated_at,expires_at=excluded.expires_at
            """,
            (
                rule_id, str(rule["title"]).strip(), str(rule["topic"]).strip(), rule["rule_type"],
                _json(triggers), str(rule["guidance"]).strip(), str(rule.get("exceptions") or "").strip(),
                str(rule.get("prohibited") or "").strip(), "active", float(rule.get("confidence", 1.0)),
                str(rule.get("source_type") or "user_explicit"), source_ref,
                int(rule.get("evidence_count", 1)), now, now, rule.get("expires_at"),
            ),
        )
        self._audit("rule_saved", "rule", rule_id, {"title": rule["title"], "source_ref": source_ref})
        self.connection.commit()
        return self._rule(self.connection.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone())

    def upsert_contact(self, name: str, role: str, email: str, cc_policy: str) -> dict[str, Any]:
        normalized = email.strip().casefold()
        if "@" not in normalized:
            raise PlaybookError("A valid email address is required")
        existing = self.connection.execute("SELECT id FROM contacts WHERE email=?", (normalized,)).fetchone()
        contact_id = str(existing["id"] if existing else uuid.uuid4())
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO contacts(id,name,role,email,cc_policy,verified_at,active,created_at,updated_at)
            VALUES(?,?,?,?,?,?,1,?,?)
            ON CONFLICT(email) DO UPDATE SET name=excluded.name,role=excluded.role,
              cc_policy=excluded.cc_policy,verified_at=excluded.verified_at,active=1,updated_at=excluded.updated_at
            """,
            (contact_id, name.strip(), role.strip(), normalized, cc_policy.strip(), now, now, now),
        )
        self._audit("contact_verified", "contact", contact_id, {"name": name, "role": role})
        self.connection.commit()
        return dict(self.connection.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone())

    def contacts(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM contacts WHERE active=1 ORDER BY name"
        ).fetchall()]

    def resolve_contacts(self, contact_ids: list[str]) -> list[dict[str, Any]]:
        if not contact_ids:
            return []
        placeholders = ",".join("?" for _ in contact_ids)
        rows = self.connection.execute(
            f"SELECT * FROM contacts WHERE active=1 AND id IN ({placeholders})", tuple(contact_ids)
        ).fetchall()
        found = {str(row["id"]): dict(row) for row in rows}
        missing = [item for item in contact_ids if item not in found]
        if missing:
            raise PlaybookError(f"Unverified or inactive contact ids: {', '.join(missing)}")
        return [found[item] for item in contact_ids]

    def record_draft(self, **event: Any) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO draft_events
            (id,draft_id,original_message_id,conversation_id,mailbox,subject,inbound_excerpt,to_json,cc_json,
             proposed_body,rules_json,created_at,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'pending')
            """,
            (
                event_id, event["draft_id"], event["original_message_id"], event.get("conversation_id"),
                str(event.get("mailbox") or "").strip().casefold(), event["subject"],
                normalize_case_excerpt(str(event.get("inbound_excerpt") or ""), 2000),
                _json(event.get("to", [])), _json(event.get("cc", [])),
                event["proposed_body"], _json(event.get("rules", [])), now,
            ),
        )
        self._audit("draft_recorded", "draft_event", event_id, {"subject": event["subject"]})
        self.connection.commit()
        return {"id": event_id, "created_at": now, "status": "pending"}

    def pending_drafts(self, max_age_days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).replace(microsecond=0).isoformat()
        rows = self.connection.execute(
            "SELECT * FROM draft_events WHERE status='pending' AND created_at>=? ORDER BY created_at LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [self._draft(row) for row in rows]

    @staticmethod
    def _draft(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for source, target in (("to_json", "to"), ("cc_json", "cc"), ("rules_json", "rules"), ("sent_cc_json", "sent_cc"), ("outcome_json", "outcome")):
            result[target] = _loads(result.pop(source), [] if target != "outcome" else {})
        return result

    def match_draft(self, event_id: str, sent: dict[str, Any], outcome: dict[str, Any]) -> None:
        now = utc_now()
        self.connection.execute(
            """
            UPDATE draft_events SET status='matched',sent_message_id=?,sent_body=?,sent_cc_json=?,
              observed_at=?,outcome_json=? WHERE id=? AND status='pending'
            """,
            (sent["id"], sent["body"], _json(sent.get("cc", [])), now, _json(outcome), event_id),
        )
        self._audit("draft_outcome_matched", "draft_event", event_id, outcome)
        self.connection.commit()

    def expire_old_drafts(self, days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        cursor = self.connection.execute(
            "UPDATE draft_events SET status='expired' WHERE status='pending' AND created_at<?", (cutoff,)
        )
        self.connection.commit()
        return cursor.rowcount

    def matched_outcomes(self, limit: int = 20, only_unreferenced: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM draft_events WHERE status='matched'"
        params: list[Any] = []
        if only_unreferenced:
            query += " AND id NOT IN (SELECT value FROM learning_proposals, json_each(evidence_event_ids_json))"
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        return [self._draft(row) for row in self.connection.execute(query, params).fetchall()]

    @staticmethod
    def _case(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["injection_signals"] = _loads(result.pop("injection_signals_json"), [])
        result["rules"] = _loads(result.pop("rules_json"), [])
        result["eligible"] = bool(result["eligible"])
        return result

    def sync_case_memory_from_matched(self, limit: int = 500) -> dict[str, int]:
        """Idempotently promote reliably matched plugin drafts into local case memory."""
        if not case_memory_enabled():
            return {"checked": 0, "created": 0, "excluded": 0}
        rows = self.connection.execute(
            """
            SELECT d.* FROM draft_events d
            LEFT JOIN email_cases c ON c.source_event_id=d.id
            WHERE d.status='matched' AND c.source_event_id IS NULL
            ORDER BY d.observed_at ASC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        created = 0
        excluded = 0
        for row in rows:
            event = self._draft(row)
            mailbox = str(event.get("mailbox") or "").strip().casefold()
            subject = normalize_case_excerpt(str(event.get("subject") or ""), 300)
            inbound = normalize_case_excerpt(str(event.get("inbound_excerpt") or ""), 2000)
            final_response = normalize_case_excerpt(str(event.get("sent_body") or ""), 3000)
            metadata = extract_case_metadata(subject, inbound)
            eligible = bool(mailbox and inbound and final_response)
            reason = "" if eligible else "missing_mailbox_or_inbound_evidence"
            case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mail-triage-case:{event['id']}"))
            self.connection.execute(
                """
                INSERT INTO email_cases
                (id,source_event_id,mailbox,conversation_id,subject,inbound_excerpt,
                 final_response_excerpt,topic,course,sender_role,injection_signals_json,
                 rules_json,created_at,resolved_at,stale_after,eligible,exclusion_reason,
                 redaction_version)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    case_id, event["id"], mailbox, event.get("conversation_id"), subject,
                    inbound, final_response, metadata["topic"], metadata["course"],
                    metadata["sender_role"], _json(metadata["injection_signals"]),
                    _json(event.get("rules", [])), event["created_at"],
                    event.get("observed_at") or event["created_at"], None, int(eligible),
                    reason, REDACTION_VERSION,
                ),
            )
            self._audit(
                "case_memory_created" if eligible else "case_memory_excluded",
                "email_case",
                case_id,
                {"source_event_id": event["id"], "reason": reason},
            )
            created += int(eligible)
            excluded += int(not eligible)
        self.connection.commit()
        return {"checked": len(rows), "created": created, "excluded": excluded}

    def upsert_historical_case(
        self,
        *,
        mailbox: str,
        sent_message_id: str,
        inbound_message_id: str,
        conversation_id: str,
        subject: str,
        inbound_text: str,
        final_response: str,
        received_at: str,
        sent_at: str,
    ) -> dict[str, Any]:
        """Store one redacted historical reply pair without raw recipient data."""
        normalized_mailbox = mailbox.strip().casefold()
        safe_subject = normalize_case_excerpt(subject, 300)
        safe_inbound = normalize_case_excerpt(inbound_text, 2000)
        safe_response = normalize_case_excerpt(final_response, 3000)
        eligible = bool(normalized_mailbox and sent_message_id and safe_inbound and safe_response)
        reason = "" if eligible else "missing_mailbox_or_historical_evidence"
        identity = f"{normalized_mailbox}:{sent_message_id}"
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mail-triage-history-event:{identity}"))
        case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mail-triage-history-case:{identity}"))
        metadata = extract_case_metadata(safe_subject, safe_inbound)
        existing = self.connection.execute(
            """
            SELECT c.id,d.id AS event_id FROM email_cases c
            JOIN draft_events d ON d.id=c.source_event_id
            WHERE c.mailbox=? AND d.sent_message_id=? LIMIT 1
            """,
            (normalized_mailbox, sent_message_id),
        ).fetchone()
        if existing:
            self.connection.execute(
                """
                UPDATE email_cases SET subject=?,inbound_excerpt=?,final_response_excerpt=?,
                  topic=?,course=?,sender_role=?,injection_signals_json=?,redaction_version=?
                WHERE id=?
                """,
                (
                    safe_subject, safe_inbound, safe_response, metadata["topic"],
                    metadata["course"], metadata["sender_role"],
                    _json(metadata["injection_signals"]), REDACTION_VERSION,
                    str(existing["id"]),
                ),
            )
            self.connection.execute(
                "UPDATE draft_events SET subject=?,inbound_excerpt=?,sent_body=? WHERE id=?",
                (safe_subject, safe_inbound, safe_response, str(existing["event_id"])),
            )
            self.connection.commit()
            return {"status": "duplicate", "case_id": str(existing["id"]), "refreshed": True}
        self.connection.execute(
            """
            INSERT OR IGNORE INTO draft_events
            (id,draft_id,original_message_id,conversation_id,mailbox,subject,inbound_excerpt,
             to_json,cc_json,proposed_body,rules_json,created_at,status,sent_message_id,
             sent_body,sent_cc_json,observed_at,outcome_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id, f"historical:{event_id}", inbound_message_id, conversation_id,
                normalized_mailbox, safe_subject, safe_inbound, "[]", "[]", "", "[]",
                received_at, "expired", sent_message_id, safe_response, "[]", sent_at,
                _json({"source": "historical_backfill", "body_changed": False}),
            ),
        )
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO email_cases
            (id,source_event_id,mailbox,conversation_id,subject,inbound_excerpt,
             final_response_excerpt,topic,course,sender_role,injection_signals_json,
             rules_json,created_at,resolved_at,stale_after,eligible,exclusion_reason,
             redaction_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                case_id, event_id, normalized_mailbox, conversation_id, safe_subject,
                safe_inbound, safe_response, metadata["topic"], metadata["course"],
                metadata["sender_role"], _json(metadata["injection_signals"]), "[]",
                received_at, sent_at, None, int(eligible), reason, REDACTION_VERSION,
            ),
        )
        self._audit(
            "historical_case_created" if eligible else "historical_case_excluded",
            "email_case",
            case_id,
            {"source": "historical_backfill", "reason": reason},
        )
        self.connection.commit()
        if cursor.rowcount == 0:
            return {"status": "duplicate", "case_id": case_id}
        return {"status": "created" if eligible else "excluded", "case_id": case_id}

    def case_memory_status(self, mailbox: str) -> dict[str, Any]:
        normalized = mailbox.strip().casefold()
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN eligible=1 THEN 1 ELSE 0 END) AS eligible,
                   SUM(CASE WHEN eligible=0 THEN 1 ELSE 0 END) AS excluded,
                   MAX(resolved_at) AS newest_resolved_at
            FROM email_cases WHERE mailbox=?
            """,
            (normalized,),
        ).fetchone()
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": case_memory_enabled(),
            "mailbox": normalized,
            "total": int(row["total"] or 0),
            "eligible": int(row["eligible"] or 0),
            "excluded": int(row["excluded"] or 0),
            "newest_resolved_at": row["newest_resolved_at"],
            "retrieval_mode": "local_deterministic_lexical_with_metadata_and_recency",
            "redaction_version": REDACTION_VERSION,
            "retention_days": case_retention_days(),
            "evidence_notice": EVIDENCE_NOTICE,
        }

    def refresh_case_redaction(self, mailbox: str) -> int:
        """Idempotently apply the current redaction rules to already stored excerpts."""
        normalized = mailbox.strip().casefold()
        rows = self.connection.execute(
            "SELECT * FROM email_cases WHERE mailbox=?", (normalized,)
        ).fetchall()
        changed = 0
        for row in rows:
            current = self._case(row)
            subject = normalize_case_excerpt(str(current["subject"]), 300)
            inbound = normalize_case_excerpt(str(current["inbound_excerpt"]), 2000)
            response = normalize_case_excerpt(str(current["final_response_excerpt"]), 3000)
            if (
                subject == current["subject"]
                and inbound == current["inbound_excerpt"]
                and response == current["final_response_excerpt"]
                and int(current["redaction_version"]) == REDACTION_VERSION
            ):
                continue
            metadata = extract_case_metadata(subject, inbound)
            self.connection.execute(
                """
                UPDATE email_cases SET subject=?,inbound_excerpt=?,final_response_excerpt=?,
                  topic=?,course=?,sender_role=?,injection_signals_json=?,redaction_version=?
                WHERE id=?
                """,
                (
                    subject, inbound, response, metadata["topic"], metadata["course"],
                    metadata["sender_role"], _json(metadata["injection_signals"]),
                    REDACTION_VERSION, current["id"],
                ),
            )
            self.connection.execute(
                "UPDATE draft_events SET subject=?,inbound_excerpt=?,sent_body=? WHERE id=?",
                (subject, inbound, response, current["source_event_id"]),
            )
            changed += 1
        if changed:
            self._audit(
                "case_redaction_refreshed", "email_case", None,
                {"mailbox": normalized, "count": changed, "redaction_version": REDACTION_VERSION},
            )
        self.connection.commit()
        return changed

    def search_cases(
        self,
        mailbox: str,
        query: str,
        *,
        topic: str = "",
        course: str = "",
        sender_role: str = "",
        limit: int = 5,
        max_age_days: int = 730,
    ) -> list[dict[str, Any]]:
        if not case_memory_enabled():
            raise PlaybookError("Case memory is disabled by configuration")
        normalized = mailbox.strip().casefold()
        rows = self.connection.execute(
            "SELECT * FROM email_cases WHERE mailbox=? AND eligible=1 ORDER BY resolved_at DESC LIMIT 2000",
            (normalized,),
        ).fetchall()
        ranked = rank_cases(
            query,
            [self._case(row) for row in rows],
            topic=topic,
            course=course,
            sender_role=sender_role,
            max_age_days=max_age_days,
        )
        return ranked[:limit]

    def case_evidence(self, mailbox: str, case_ids: list[str]) -> list[dict[str, Any]]:
        if not case_memory_enabled():
            raise PlaybookError("Case memory is disabled by configuration")
        normalized = mailbox.strip().casefold()
        unique_ids = list(dict.fromkeys(case_ids))
        if not unique_ids:
            return []
        placeholders = ",".join("?" for _ in unique_ids)
        rows = self.connection.execute(
            f"SELECT * FROM email_cases WHERE mailbox=? AND id IN ({placeholders})",
            (normalized, *unique_ids),
        ).fetchall()
        found = {str(row["id"]): self._case(row) for row in rows}
        missing = [case_id for case_id in unique_ids if case_id not in found]
        if missing:
            raise PlaybookError("Case evidence not found in the authenticated mailbox")
        return [found[case_id] for case_id in unique_ids]

    def proposal_event_ids_from_cases(self, mailbox: str, case_ids: list[str]) -> list[str]:
        unique_ids = list(dict.fromkeys(case_ids))
        if len(unique_ids) < 2:
            raise PlaybookError("At least two independent cases are required")
        cases = self.case_evidence(mailbox, unique_ids)
        now = datetime.now(timezone.utc)
        conversations: set[str] = set()
        event_ids: list[str] = []
        for case in cases:
            if not case["eligible"] or not case["inbound_excerpt"] or not case["final_response_excerpt"]:
                raise PlaybookError("All proposal cases must contain eligible evidence")
            if case["injection_signals"]:
                raise PlaybookError("Cases containing prompt-injection signals cannot support a rule proposal")
            resolved = datetime.fromisoformat(str(case["resolved_at"]).replace("Z", "+00:00"))
            if resolved.tzinfo is None:
                resolved = resolved.replace(tzinfo=timezone.utc)
            if (now - resolved).days > case_retention_days():
                raise PlaybookError("Expired cases cannot support a rule proposal")
            conversation = str(case.get("conversation_id") or case["source_event_id"])
            if conversation in conversations:
                raise PlaybookError("Rule proposals require independent conversations")
            conversations.add(conversation)
            event_ids.append(str(case["source_event_id"]))
        return event_ids

    def prune_case_memory(self, days: int | None = None) -> int:
        retention = case_retention_days() if days is None else min(max(int(days), 1), 3650)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).replace(microsecond=0).isoformat()
        cursor = self.connection.execute(
            """
            UPDATE email_cases
            SET subject='',inbound_excerpt='',final_response_excerpt='',eligible=0,
                exclusion_reason='retention_expired',injection_signals_json='[]'
            WHERE resolved_at<? AND
              (eligible=1 OR subject<>'' OR inbound_excerpt<>'' OR final_response_excerpt<>'')
            """,
            (cutoff,),
        )
        if cursor.rowcount:
            self._audit("case_memory_pruned", "email_case", None, {"count": cursor.rowcount})
        self.connection.commit()
        return cursor.rowcount

    def create_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        rule_type = str(proposal.get("rule_type") or "")
        if rule_type not in ALLOWED_RULE_TYPES:
            raise PlaybookError(f"Unsupported rule_type: {rule_type}")
        evidence_ids = list(dict.fromkeys(str(item) for item in proposal.get("evidence_event_ids", [])))
        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            count = self.connection.execute(
                f"SELECT COUNT(*) FROM draft_events WHERE status='matched' AND id IN ({placeholders})",
                tuple(evidence_ids),
            ).fetchone()[0]
            if count != len(evidence_ids):
                raise PlaybookError("Every evidence event must be a matched draft outcome")
        risk = str(proposal.get("risk_level") or "high")
        if risk not in {"low", "medium", "high"}:
            raise PlaybookError("risk_level must be low, medium, or high")
        auto = (os.getenv("OUTLOOK_AUTO_LEARN_STYLE", "0").casefold() in {"1", "true", "yes"}
                and rule_type == "style" and risk == "low" and len(evidence_ids) >= 3)
        status = "auto_approved" if auto else "pending"
        proposal_id = str(uuid.uuid4())
        now = utc_now()
        rule_json = dict(proposal["rule"])
        rule_json.update({"rule_type": rule_type, "evidence_count": max(1, len(evidence_ids)), "source_type": "post_send_observation"})
        self.connection.execute(
            """
            INSERT INTO learning_proposals
            (id,title,topic,rule_type,rule_json,rationale,risk_level,evidence_event_ids_json,
             evidence_count,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                proposal_id, proposal["title"], proposal["topic"], rule_type, _json(rule_json),
                proposal["rationale"], risk, _json(evidence_ids), len(evidence_ids), status, now, now,
            ),
        )
        if auto:
            self.remember_rule(rule_json, source_ref=f"proposal:{proposal_id}")
        else:
            question = str(proposal.get("question") or f"Should I adopt this rule: {proposal['title']}?")
            self.connection.execute(
                "INSERT INTO feedback_questions(id,proposal_id,question,status,created_at) VALUES(?,?,?,'pending',?)",
                (str(uuid.uuid4()), proposal_id, question, now),
            )
        self._audit("proposal_created", "learning_proposal", proposal_id, {"status": status, "risk": risk})
        self.connection.commit()
        return self.proposal(proposal_id)

    def proposal(self, proposal_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM learning_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            raise PlaybookError("Proposal not found")
        result = dict(row)
        result["rule"] = _loads(result.pop("rule_json"), {})
        result["evidence_event_ids"] = _loads(result.pop("evidence_event_ids_json"), [])
        return result

    def pending_proposals(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id FROM learning_proposals WHERE status='pending' ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()
        return [self.proposal(str(row["id"])) for row in rows]

    def review_proposal(self, proposal_id: str, decision: str) -> dict[str, Any]:
        if decision not in ALLOWED_PROPOSAL_DECISIONS:
            raise PlaybookError("decision must be approve or reject")
        proposal = self.proposal(proposal_id)
        if proposal["status"] != "pending":
            raise PlaybookError("Proposal is not pending")
        now = utc_now()
        status = "approved" if decision == "approve" else "rejected"
        self.connection.execute(
            "UPDATE learning_proposals SET status=?,updated_at=? WHERE id=?", (status, now, proposal_id)
        )
        if decision == "approve":
            self.remember_rule(proposal["rule"], source_ref=f"proposal:{proposal_id}")
        self.connection.execute(
            "UPDATE feedback_questions SET status='dismissed' WHERE proposal_id=? AND status='pending'", (proposal_id,)
        )
        self._audit("proposal_reviewed", "learning_proposal", proposal_id, {"decision": decision})
        self.connection.commit()
        return self.proposal(proposal_id)

    def optional_questions(self, limit: int = 2) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT id,proposal_id,question,created_at FROM feedback_questions WHERE status='pending' ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()]

    def record_feedback(self, question_id: str, answer: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM feedback_questions WHERE id=? AND status='pending'", (question_id,)
        ).fetchone()
        if not row:
            raise PlaybookError("Pending feedback question not found")
        now = utc_now()
        self.connection.execute(
            "UPDATE feedback_questions SET status='answered',answer=?,answered_at=? WHERE id=?",
            (answer.strip(), now, question_id),
        )
        self._audit("feedback_recorded", "feedback_question", question_id, {"proposal_id": row["proposal_id"]})
        self.connection.commit()
        return {"id": question_id, "proposal_id": row["proposal_id"], "status": "answered", "answer": answer.strip()}

    def export_sanitized(self, include_audit: bool = False) -> dict[str, Any]:
        result = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": utc_now(),
            "rules": self.list_rules("active"),
            "contacts": [
                {key: item[key] for key in ("id", "name", "role", "email", "cc_policy", "verified_at")}
                for item in self.contacts()
            ],
            "pending_proposals": self.pending_proposals(100),
        }
        if include_audit:
            result["audit"] = [dict(row) for row in self.connection.execute(
                "SELECT occurred_at,event_type,object_type,object_id,details_json FROM audit_log ORDER BY id DESC LIMIT 500"
            ).fetchall()]
        return result

    def prune_observation_text(self, days: int = 90) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        cursor = self.connection.execute(
            """
            UPDATE draft_events SET proposed_body='',sent_body=''
            WHERE created_at<? AND (proposed_body<>'' OR COALESCE(sent_body,'')<>'')
            """,
            (cutoff,),
        )
        self.connection.commit()
        return cursor.rowcount
