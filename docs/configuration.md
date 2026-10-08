# Configuration

No personal identity, contact list, writing profile, routing rules, or mailbox data ships with this project. Set environment variables in your shell, service environment, or MCP host. `.env.example` documents them but is not loaded automatically.

| Setting | Default / purpose |
| --- | --- |
| `OUTLOOK_GRAPH_CLIENT_ID` | Required: your Entra public-client application ID |
| `OUTLOOK_GRAPH_AUTHORITY` | `https://login.microsoftonline.com/organizations` |
| `OUTLOOK_MSAL_CACHE` | `~/.local/share/mail-triage/msal-cache.json` |
| `OUTLOOK_PLAYBOOK_DB` | `~/.local/share/mail-triage/playbook.sqlite3` |
| `OUTLOOK_PROFILE_FILE` | `~/.config/mail-triage/profile.toml` |
| `OUTLOOK_AUTO_LEARN_STYLE` | `0`; set `1` to allow eligible style proposals to auto-activate |
| `OUTLOOK_CASE_MEMORY_ENABLED` | `1`; set `0` to stop new case synchronization/retrieval |
| `OUTLOOK_CASE_RETENTION_DAYS` | `365`, clamped to 30–3650 days |
| `OUTLOOK_MCP_TRANSPORT` | `stdio`; remote mode is `streamable-http` |
| `OUTLOOK_MCP_HTTP_HOST` | `127.0.0.1` |
| `OUTLOOK_MCP_HTTP_PORT` | `8765` |
| `OUTLOOK_MCP_PUBLIC_BASE_URL` | Empty; required for HTTP OAuth, e.g. `https://mail-triage.example.com` |
| `OUTLOOK_MCP_OAUTH_DB` | `~/.local/share/mail-triage/oauth.sqlite3` |

`~` means the deployment user's home directory. Keep the same environment in the MCP server, login command, pairing command, and observer. Use separate directories and databases for separate owners.

## Voice and signature

Copy `examples/profile.example.toml` to your private profile location, then replace its fictional content. `get_email_voice` uses generic guidance when no profile exists. A private `[voice]` section supplies your preferred name and guidance array. `[signature]` supplies optional text and explicit names whose duplicate short closing may be removed. Without a configured signature, the server preserves the proposed closing.

The profile is read when used. It is not automatically rewritten from Sent Items. Ask the assistant to analyze a bounded sample only if desired, review the proposed guidance, and save it locally yourself or explicitly authorize that file edit. Approved playbook style rules can evolve separately.

`[[reference_contacts]]` entries provide name, role, email, keywords, and source. They are informational only. A fresh playbook's verified-contact registry is empty; adding a reference does not add it to that registry. Verify each recipient and its CC policy explicitly before using `upsert_verified_contact`.

## Persistence

Environment exports usually last only for the current shell. `configure_mcp.py` embeds the app ID and stdio transport in the machine-local connection, while other overrides must be supplied by the host or service environment. You may add your own profile/state overrides to that ignored configuration. Never check it into Git or upload it with a public plugin ZIP.
