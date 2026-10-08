# Quickstart

Use Python 3.11 or newer. Try the demo first; it never accesses mail. The application reads environment variables directly and does **not** automatically load `.env` files.

## Install

```bash
git clone https://github.com/i-xoxol/self-learning-mail-triage.git
cd self-learning-mail-triage
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/demo.py
```

On Windows PowerShell, use `.venv\Scripts\Activate.ps1`. If your execution policy prevents activation, run `.venv\Scripts\python.exe` directly for every Python command.

## Register and authenticate

Follow [authentication](authentication.md) to create your own Entra public-client app. Do not reuse someone else's app registration or token cache.

PowerShell:

```powershell
$env:OUTLOOK_GRAPH_CLIENT_ID = 'YOUR_APPLICATION_ID'
python scripts/authenticate.py
python scripts/configure_mcp.py
```

Linux/macOS:

```bash
export OUTLOOK_GRAPH_CLIENT_ID='YOUR_APPLICATION_ID'
python scripts/authenticate.py
python scripts/configure_mcp.py
```

Review [privacy](privacy.md) before connecting: mailbox previews reach your assistant, and draft-versus-sent comparison retains local text. Defaults keep authentication and learning state outside this checkout. The generated `.mcp.local.json` contains absolute paths and your application ID, is ignored by Git, and uses the Python interpreter running the setup command. Run configuration from the installed virtual environment.

## Connect an MCP client

Copy the `mail_triage` server entry from `.mcp.local.json` into your client's MCP configuration, adapting the wrapper and approval settings to that host's format. Load `skills/mail-triage/SKILL.md` as the companion workflow. The server's command and arguments are already absolute, so it can start from another working directory. Keep confirmations enabled for mutation tools.

### Codex desktop plugin

This repository includes the supported Codex compatibility layout and a repo-local marketplace. Configure the server **before** installing the plugin; its manifest references generated `.mcp.local.json`.

From the checkout:

```bash
codex plugin marketplace add .
```

Open the supported desktop client's Plugins Directory, select **Self-learning Mail Triage — local**, and install **Self-learning Mail Triage**. Restart or refresh the local install after changing source or connection settings. The installed plugin copy refers to the original checkout's interpreter and server paths, so keep that checkout and virtual environment available. For a remote endpoint, generate the connection with `python scripts/configure_mcp.py --remote-url https://YOUR_HOST/mcp` first.

Local installation depends on client support; this repository is not a universal plugin-directory listing. The format and marketplace process follow [OpenAI's plugin packaging documentation](https://developers.openai.com/plugins/build/plugins).

## First run

Ask: “Review my unread inbox. Keep messages requiring a decision or reply unread, and show a complete plan. Prepare unsent replies only when their substance is clear.”

Check the proposed summaries and reasons. Approve the exact actions you want. The server refuses unconfirmed or incomplete plans. When you send a prepared reply yourself, authorize observation and ask the assistant to compare outcomes and suggest useful preferences.

Optional private voice and signature setup is in [configuration](configuration.md). Automatic style activation is off; enable it only after understanding the [learning gates](learning.md).

## Verify without an account

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
python scripts/check_mcp.py
python scripts/audit_public_source.py
```
