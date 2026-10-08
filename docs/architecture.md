# Architecture and boundaries

| Component | Responsibility |
| --- | --- |
| `mcp_server.py` | Tool schemas, snapshots, plan validation, draft creation, learning API |
| `mailbox_graph.py` | Delegated `/me` Graph access, device login, silent acquisition, safe reply HTML |
| `runtime_profile.py` | Optional private voice, signature, and contact reference |
| `playbook_store.py` | Rules, verified contacts, outcomes, cases, proposals, questions, audit |
| `draft_observer.py` | Conversation-based draft matching and comparison |
| `case_memory.py` | Best-effort redaction, metadata, injection warnings, deterministic ranking |
| `historical_backfill.py` | Bounded conversation pairing and idempotent import |
| `oauth_provider.py` | Single-owner remote pairing, expiring tokens, refresh rotation |
| `skills/mail-triage/` | Host reasoning workflow and authorization requirements |

Snapshots live in memory for two hours. The plan must include every snapshot ID exactly once and a valid action, importance, summary, and reason. Before mutating, the server checks the authenticated mailbox, Inbox, subject, and internet message identity. Marking read happens before archiving. Failures are reported per item; Graph mutations are not a transaction and can partially succeed.

Draft creation validates the source snapshot and resolves added CC IDs against the verified registry. It saves the proposed reply and the outcome reference in SQLite after Graph creates the draft. A database failure can therefore leave a draft without an observation record; check Outlook before retrying.

The server enforces confirmation booleans, permitted tools, identity checks, and structural rule gates. The host must determine that confirmation actually comes from the user, facts are sufficient, CC policy permits routing, and a style proposal is semantically low-risk. Email text cannot supply that authorization.

The Graph client refuses other hosts and non-`/me` paths and disables redirect following. Exposed tools cannot send, delete, forward, or edit mailbox rules. Delegated `Mail.ReadWrite` itself is broader than the constrained tool surface, so cache access remains sensitive.

Case queries enforce mailbox scope. Rules, contacts, pending outcomes, and exports assume one owner; this is not tenant isolation for a shared service. Run separate processes with separate caches and databases for separate users.
