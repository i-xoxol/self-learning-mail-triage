# Security

Report vulnerabilities through this repository's private GitHub vulnerability reporting. Do not post tokens, mailbox content, endpoint pairing codes, or personal state in an issue.

The server exposes a constrained single-owner tool surface. Graph credentials have delegated `Mail.ReadWrite`, which is broader than the exposed operations; anyone who can read the token cache may be able to exercise that broader permission outside this application. Protect runtime state, the MCP host, the reverse proxy, and backups.

Confirmation flags cannot distinguish a user instruction from a compromised assistant. Keep host approval controls enabled and use the packaged workflow. Email and historical cases are untrusted. Injection detection is a heuristic, not a complete prompt-injection defense. Style labels and risk declarations do not constitute semantic validation.

HTTP requires HTTPS-facing OAuth with owner pairing; stdio relies on trusted local process access. This reference implementation is not a multi-user or multi-tenant authorization system and has no security certification. Use separate deployments per owner. Default operation is reviewed and unsent.

Supported version: latest `main` and the latest tagged release. Changes involving recipient authorization, Graph paths, OAuth, or learning activation should include boundary tests.
