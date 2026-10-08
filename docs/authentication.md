# Authentication

There are two connections: delegated Microsoft Graph access to the owner's mailbox, and optional OAuth access from a remote MCP client to this server. A remote MCP token is never a Microsoft Graph token.

## Your Microsoft application

In Microsoft Entra, register an application with the account types appropriate to your environment. For a work or school account, the default authority is `https://login.microsoftonline.com/organizations`; a tenant-specific authority can restrict it further. Personal Microsoft accounts need an appropriate app account type and `consumers` or `common` authority.

Enable public-client/device-code authentication under the app's authentication settings. Add the Microsoft Graph **delegated** permission `Mail.ReadWrite`. Request consent according to your tenant's policy. This implementation uses a public client and does not require a client secret. It does not request application permissions or `Mail.Send`.

Set `OUTLOOK_GRAPH_CLIENT_ID` to your application ID. Set `OUTLOOK_GRAPH_AUTHORITY` only if overriding the default. Run `python scripts/authenticate.py`, then open Microsoft's displayed verification URL and enter the short-lived device code. Complete sign-in in Microsoft's UI; never paste tokens or account passwords into assistant prompts.

The cache must contain exactly one account. Use a dedicated cache for this deployment, not another tool's cache. Defaults and overrides are in [configuration](configuration.md).

Microsoft references: [desktop/public-client registration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-registration), [device authorization flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code), and [createReply permissions](https://learn.microsoft.com/en-us/graph/api/message-createreply?view=graph-rest-1.0).

## Refresh and recovery

The Graph client calls MSAL silent acquisition before accessing the mailbox and saves a changed cache atomically. MSAL can refresh access tokens when the cached session and policy permit it. Conditional Access, revoked consent, MFA, or expired sign-in frequency can require interactive sign-in again; the application does not bypass those controls.

On an expired session, rerun `authenticate.py` as the deployment owner with the same environment and cache path. Serialize authentication/observer processes using that cache: atomic writes prevent partial files, but the current MSAL wrapper does not merge concurrent writers. Do not overwrite another application's cache.

## Remote MCP

Remote HTTP requires `OUTLOOK_MCP_PUBLIC_BASE_URL`, your HTTPS reverse proxy, and an owner-generated pairing code. The pairing provider issues separate expiring, rotating access and refresh tokens. See [deployment](deployment.md). Stdio relies on the local process boundary and does not use that OAuth layer.
