"""Read an optional private TOML profile; ship no owner's voice or contacts."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = Path.home() / '.config' / 'mail-triage' / 'profile.toml'


def profile() -> dict[str, Any]:
    path = Path(os.getenv('OUTLOOK_PROFILE_FILE', str(DEFAULT_PROFILE))).expanduser()
    if not path.is_file():
        return {}
    with path.open('rb') as handle:
        return tomllib.load(handle)


def email_voice() -> dict[str, Any]:
    settings = profile()
    voice = settings.get('voice', {})
    return {
        'profile_name': voice.get('name', 'General email voice'),
        'source': 'user-configured local guidance' if voice else 'generic defaults; no mailbox analysis',
        'core': voice.get('guidance', [
            'Lead with the answer or the practical next step.',
            'Use plain language, short paragraphs, and a courteous tone.',
            'Match the requested level of detail and formality.',
            'Do not invent decisions, policies, availability, or commitments.',
        ]),
        'required_signature': settings.get('signature', {}).get('text', ''),
    }


def reference_contacts() -> list[dict[str, Any]]:
    """Local references are informational; only the verified registry can add CC."""
    return profile().get('reference_contacts', [])


def with_signature(reply_text: str) -> str:
    text = reply_text.strip()
    settings = profile().get('signature', {})
    signature = str(settings.get('text', '')).strip()
    if not signature or text.endswith(signature):
        return text
    # Strip only a closing belonging to an explicitly configured owner name.
    for name in settings.get('closing_names', []):
        text = re.sub(
            r'(?is)\n{1,3}(?:best|best regards|kind regards|regards|sincerely)[,!]?\s*\n'
            + re.escape(str(name)) + r'\.?\s*$', '', text,
        ).rstrip()
    return f'{text}\n\n{signature}'
