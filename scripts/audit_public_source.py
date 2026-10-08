"""Check publishable files for runtime state and common credential patterns.

This is a guardrail, not proof of comprehensive sanitization. Review the staged
diff and full file list before publishing. It prints paths/reasons, never values.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRECTORIES = {'.git', '.venv', '__pycache__', 'state', 'private', 'exports'}
PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'JWT': re.compile(r'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b'),
    'private LAN address': re.compile(r'\b(?:192\.168|10\.\d+)\.\d+\.\d+\b'),
}


def public_files() -> list[Path]:
    if (ROOT / '.git').exists():
        result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True)
        return [ROOT / name.decode('utf-8') for name in result.stdout.split(b'\0') if name]
    return [path for path in ROOT.rglob('*') if path.is_file()
            and not set(path.relative_to(ROOT).parts) & SKIP_DIRECTORIES
            and path.name != '.mcp.local.json']


def main() -> int:
    files = public_files()
    problems = []
    for path in files:
        relative = str(path.relative_to(ROOT))
        if (path.suffix in {'.sqlite3', '.sqlite', '.db', '.pem', '.key', '.pfx', '.p12'}
                or path.name in {'.env', 'profile.toml', '.mcp.local.json'}
                or path.name.endswith(('-wal', '-shm')) or 'msal-cache' in path.name):
            problems.append((relative, 'runtime data or credential filename'))
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeError, OSError):
            problems.append((relative, 'unexpected binary/unreadable file; review manually'))
            continue
        for reason, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append((relative, reason))
        for address in re.findall(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})', text):
            address = address.casefold()
            if not (address in {'example.com', 'example.org', 'example.net', 'example.edu', 'users.noreply.github.com'}
                    or address.endswith(('.example', '.test'))):
                problems.append((relative, 'non-example email domain; review manually'))
    if problems:
        for path, reason in sorted(set(problems)):
            print(f'{path}: {reason}')
        return 1
    print(f'Public source audit passed: {len(files)} text/vector files; no runtime state or common credential patterns.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
