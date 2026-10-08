# Deployment

Start with local stdio from the [quickstart](quickstart.md). HTTP is an optional single-owner deployment for remote MCP clients. This project provides no shared hosted service.

## Remote HTTP

Install under your own account, create a virtual environment, authenticate with your own Entra app, and keep state in an owner-restricted directory. Set:

```bash
export OUTLOOK_GRAPH_CLIENT_ID='YOUR_APPLICATION_ID'
export OUTLOOK_MCP_TRANSPORT='streamable-http'
export OUTLOOK_MCP_HTTP_HOST='127.0.0.1'
export OUTLOOK_MCP_HTTP_PORT='8765'
export OUTLOOK_MCP_PUBLIC_BASE_URL='https://mail-triage.example.com'
python scripts/mcp_server.py
```

Replace the fictional public hostname with your endpoint. Terminate TLS through your own reverse proxy and forward the MCP, OAuth discovery/authorization/token, approval, and health routes to the loopback process. Keep OAuth enabled, restrict direct backend access, and configure proxy rate limits for authorization/approval routes. The server applies allowed-host checks for the public host and loopback. `/healthz` is an unauthenticated liveness response, not an authentication or learning-health check.

The HTTP server refuses startup without a public HTTPS base URL. A pairing provider is required for remote access. Generate a one-time code in your trusted deployment shell:

```bash
python scripts/mcp_pairing.py --base-url https://mail-triage.example.com
```

Connect your remote client to `https://mail-triage.example.com/mcp`. Enter the displayed code only on your endpoint's authorization page after checking the requesting client and callback host. Pairing codes expire in 15 minutes and are single-use. Access tokens last one hour; refresh tokens rotate and have a 90-day lifetime. Pairing establishes access to the owner's tools, so issue a code only to a client you trust.

Generate a private plugin connection with `python scripts/configure_mcp.py --remote-url https://mail-triage.example.com/mcp`, then install/refresh the local plugin. Hosting the endpoint and creating a GitHub repository do not submit the plugin to an app directory.

## Optional Linux services

`deploy/systemd/` contains user-service templates using `~/apps/self-learning-mail-triage`. Adjust that path if needed. Create `~/.config/mail-triage/service.env` with your application ID, HTTPS base URL, and any private-state overrides; restrict it to the owner. It uses systemd environment-file syntax, not shell `export` statements.

Copy the desired units to `~/.config/systemd/user/`, run `systemctl --user daemon-reload`, then enable the HTTP service or observer timer. Authentication must already exist; services cannot complete interactive login. Check `journalctl --user -u mail-triage-mcp.service` and `systemctl --user list-timers` after setup.

The observer timer only compares draft outcomes. It does not classify mail or create proposals without an assistant. Schedule an assistant run separately only when desired and with explicit standing authorization. Avoid concurrent observer/login/cache writers; the included timer is optional and off until enabled.
