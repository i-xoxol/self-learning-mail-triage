"""Generate a one-time pairing code for the remote MCP OAuth flow."""

from __future__ import annotations

import argparse
import os

from oauth_provider import PairingOAuthProvider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=os.getenv("OUTLOOK_MCP_OAUTH_DB", "~/.local/share/mail-triage/oauth.sqlite3"))
    parser.add_argument("--base-url", default=os.getenv("OUTLOOK_MCP_PUBLIC_BASE_URL", ""))
    parser.add_argument("--minutes", type=int, default=15)
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        parser.error("--base-url or OUTLOOK_MCP_PUBLIC_BASE_URL must specify your HTTPS endpoint")
    provider = PairingOAuthProvider(args.database, args.base_url)
    code = provider.create_pairing_code(max(1, args.minutes) * 60)
    print(f"One-time pairing code (expires in {max(1, args.minutes)} minutes): {code}")


if __name__ == "__main__":
    main()
