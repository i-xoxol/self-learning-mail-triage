# MCP tool reference

All tools belong to the configured `mail_triage` server. “Read-only” below refers to the mailbox; several tools still maintain local memory. Exact argument schemas are available through MCP `tools/list`.

| Group | Tools | Effects |
| --- | --- | --- |
| Connection | `authentication_status` | Silent token acquisition; may refresh the private cache |
| Inbox | `list_unread_inbox` | Reads unread previews; creates a two-hour in-memory snapshot |
| Voice / references | `get_email_voice`, `lookup_reference_contacts` | Reads the optional private profile; reference lookup never authorizes CC |
| Sent sample | `list_recent_sent_samples` | Reads up to 100 Sent Items for explicitly requested style analysis; omits recipients and quoted history |
| Rules | `get_relevant_email_rules`, `list_email_rules` | Reads local active/inactive rules |
| Direct rule | `remember_email_rule` | Writes an explicitly approved rule; requires confirmation |
| Contacts | `list_verified_contacts`, `upsert_verified_contact` | Registry read / confirmed registry write |
| Triage | `apply_triage_plan` | Confirmed complete plan; keep unread, mark read, or mark read then archive |
| Draft | `create_reply_draft` | Confirmed unsent reply with optional configured signature and verified CC; records an outcome event |
| Observation | `observe_draft_outcomes`, `list_draft_outcomes` | Reads Sent Items and maintains local evidence / reads matched evidence |
| Proposal | `propose_rule_update`, `list_pending_rule_updates`, `review_rule_update` | Creates a proposal, lists pending proposals, or confirms review; opt-in style proposals can activate |
| Feedback | `get_optional_feedback_questions`, `record_learning_feedback` | Reads optional questions / confirms an answer; an answer alone does not approve a rule |
| Cases | `get_case_memory_status`, `search_similar_email_cases`, `get_case_evidence` | Mailbox-scoped local health, maintenance, and advisory evidence |
| Case proposal | `propose_rule_from_cases` | Confirmed proposal using independent eligible cases; non-style activation still requires review |
| Export | `export_email_playbook` | Returns rules, contacts, proposals, and optional audit; export remains private data |

Mutation tools default to `confirmed=false`. A flag is a machine-enforced gate, not independent proof of user authorization. Configure client approval prompts as well as following the skill.

Unread inventory uses bounded previews, not full attachments or complete message bodies. Use an authorized complementary source when a meaningful reply depends on missing context. The optional history CLI has a separate `--confirmed` gate for local storage; it is not an automatic setup step.
