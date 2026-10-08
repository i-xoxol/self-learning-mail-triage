# Learning from reviewed work

Learning happens in a local SQLite playbook. The assistant reasons over evidence; the server records outcomes and enforces structural gates. No model weights are trained, no embedding service is required, and no assistant runs automatically inside the observer.

## The loop

1. Create an authorized unsent draft using current facts and active rules.
2. The owner edits and sends it through Outlook.
3. An authorized read-only observer searches Sent Items for a later message in the same conversation, with subject similarity as an additional signal.
4. Store a matched outcome with body similarity, length change, and CC differences; create one idempotent, redacted case.
5. Retrieve relevant cases and ask the assistant to propose a consistent, useful preference.
6. Review the proposal, then use approved guidance on future messages.

Conversation matching is a heuristic. Multiple later replies can make attribution ambiguous, and the observer may miss old drafts or messages outside its bounded Sent Items scan. A changed CC can inform a proposal but never verifies a new contact. Review evidence before adopting anything consequential.

## What can activate

| Proposal | Activation |
| --- | --- |
| Style, automatic learning off | Explicit owner review |
| Declared low-risk style, automatic learning on, at least three matched outcome IDs | May auto-activate |
| Style with insufficient evidence or higher declared risk | Explicit owner review |
| Operational, routing, recipient, or safety | Explicit owner review regardless of count |

The structural gate checks declared type, risk, matched evidence, and opt-in. It does not prove semantic safety or that all evidence shares the same pattern. The companion skill tells the assistant to reject misleading labels and identify consistent wording changes. Direct outcome proposals count distinct events; case-grounded proposals additionally require independent eligible conversations. Set `OUTLOOK_AUTO_LEARN_STYLE=0` for full manual review.

## Retrieval

Ranking combines lexical overlap, deterministic topic/role metadata, an optional course tag, and recency. Broad tags include billing, project, support, meeting, administration, and research; education-related tags are optional heuristics, not institutional policy. All retrieved text carries an evidence warning. Injection-like content is flagged and excluded from case-grounded proposals.

Precedence is hard safety, approved rules, current message facts, then historical examples. A previous promise, deadline, availability, or recipient never becomes current authority merely because it appears in memory.

## Optional historical bootstrap

Only after authorizing both access and local retention:

```bash
python scripts/backfill_history.py --days 365 --max-sent 10000 --max-mailbox-messages 30000 --confirmed
```

The import pairs authored Sent Items with the closest earlier inbound message in each conversation. It skips recognized automated replies and owner-authored inbound records, stores redacted bounded cases, and deduplicates repeated imports. It reads mailbox history and does not mutate mail. Inspect its limit counters; reaching a bound means coverage is partial.

`query_case_memory.py "meeting confirmation"` prints metadata by default; `--include-redacted-excerpts` intentionally exposes the bounded evidence. `refresh_case_redaction.py` reapplies the current redactor. Both require mailbox authentication. Retention is described in [privacy](privacy.md).
