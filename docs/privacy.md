# Data and retention

The public repository contains source, tests, and fictional examples only. A running deployment processes real email. “Local” describes storage location; the MCP client and its model provider can also receive tool results and draft content according to their own policies.

| Data | Location / handling |
| --- | --- |
| Microsoft account tokens | Dedicated MSAL cache; sensitive, unencrypted application file |
| Remote client tokens and registrations | Optional OAuth SQLite database; token indexes are hashed but model payloads remain sensitive |
| Inbox previews | In-memory snapshots for two hours; returned to the assistant |
| Proposed and matched sent bodies | Local draft events; body text cleared after 90 days during observer maintenance |
| Inbound case input | Bounded redacted excerpt in draft events |
| Resolved case excerpts | Redacted, bounded SQLite cases; default content retention 365 days |
| Message / conversation IDs, subjects, recipients, outcome metadata | Local event records; some remain after body pruning |
| Rules, verified contacts, feedback, audit | Local SQLite; retained until the owner removes their state |
| Voice, signature, contact reference | Optional private TOML file |

Pruning runs during observation/case maintenance, not by time alone. Case retention clears case text and eligibility while preserving identity metadata for deduplication. It does not erase event subjects, recipient fields, feedback, audit entries, backups, or SQLite remnants. Turning off case memory does not disable draft-event recording or erase existing state.

Redaction removes common emails, URLs, phone numbers, long identifiers, token-like strings, quoted history, and recognizable signature footers. It is not comprehensive anonymization. Names, ordinary numbers, confidential meaning, or unusual credentials can survive. Do not assume excerpts are suitable for public sharing.

## Protect state

Keep runtime files outside the checkout on an owner-restricted directory. Unix file modes are applied to new cache/database files where supported; Windows users should set restrictive ACLs. Use filesystem encryption and encrypted backups when required. The application does not encrypt SQLite or the MSAL cache. SQLite WAL/SHM files and service logs can also contain private information.

Do not upload playbook exports: they intentionally include rules and contact addresses, and optional audit can include sensitive details. Avoid posting mailbox errors verbatim in public issues. The observer CLI prints mailbox and outcome metadata; protect or minimize its journal retention.

## Backup and removal

Stop the server and observer before backup. Copy private state with the matching SQLite sidecar files, or use SQLite's backup facility; protect the backup as strongly as the original. Do not commit a backup.

To remove local data, stop all processes and remove your dedicated runtime directory, its SQLite sidecars, private profile, exports, and backups after verifying the paths. Revoke app consent and remote client connections through the relevant account settings if you are retiring access. Local file removal does not erase content already sent to your assistant provider or messages stored in Outlook.
