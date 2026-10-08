# Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing application ID | Set your own `OUTLOOK_GRAPH_CLIENT_ID`; `.env.example` is documentation, not an automatically loaded file. |
| Consent or device-flow failure | Confirm public-client/device flow settings, delegated permission, account type, authority, and tenant policy. |
| Expired authentication | Rerun `authenticate.py` under the service owner and same cache path. Silent refresh cannot override sign-in policy. |
| Multiple cached accounts | Use a dedicated single-account cache; do not edit token JSON by hand. |
| Plugin cannot find MCP config | Run `configure_mcp.py` from the virtual environment before installing; refresh the installed copy afterward. |
| Server cannot import MCP | Use the environment's Python, reinstall pinned dependencies, and regenerate machine-local command paths. |
| Snapshot missing / expired | Request a fresh unread snapshot and rebuild the complete plan. Server restarts clear snapshots. |
| Plan rejected | Include every snapshot ID exactly once, valid fields, and actual user authorization before setting confirmation. |
| Partial archive | Check returned per-item status; the original may already be read. Fetch a fresh snapshot before retrying. |
| Draft exists but is not observed | A database error can follow successful Graph draft creation. Inspect Outlook before creating another draft. |
| Outcome did not match | Check conversation IDs, creation/sent dates, pending expiry, scan limits, and whether the owner actually sent the draft. |
| Cases appear incomplete | Check import bounds, retention, eligibility, mailbox scope, and metadata heuristics. |
| Rules never auto-activate | Default manual review is intentional. Style opt-in still requires low declared risk and three matched outcomes. |
| Remote connection fails | Check TLS, all OAuth routes, public base URL, backend loopback/proxy access, and pairing expiry. |

Run offline tests and `check_mcp.py` to distinguish local setup failures from account policy or Graph failures. Share redacted diagnostics only; never publish caches, message bodies, personal paths, connection files, or database exports.
