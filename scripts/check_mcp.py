"""Exercise a real stdio MCP handshake with no mailbox connection."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check() -> None:
    with tempfile.TemporaryDirectory(prefix='mail-triage-mcp-check-') as directory:
        # Ignore any live account or hosted-server settings in the invoking shell.
        environment = {key: value for key, value in os.environ.items() if not key.startswith('OUTLOOK_')}
        environment['OUTLOOK_MCP_TRANSPORT'] = 'stdio'
        environment['OUTLOOK_PROFILE_FILE'] = str(Path(directory) / 'missing.toml')
        environment['OUTLOOK_PLAYBOOK_DB'] = str(Path(directory) / 'test.sqlite3')
        parameters = StdioServerParameters(command=sys.executable,
            args=[str(Path(__file__).with_name('mcp_server.py'))], env=environment)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {'list_unread_inbox', 'create_reply_draft', 'search_similar_email_cases'} <= names
                assert not any(any(word in name for word in ('delete', 'send_mail', 'unsubscribe', 'forward')) for name in names)
                voice = await session.call_tool('get_email_voice', {})
                assert not voice.isError
                contacts = await session.call_tool('lookup_reference_contacts', {'query': 'support'})
                assert not contacts.isError
                print(f'MCP handshake passed: {len(names)} constrained tools; generic voice and empty contact references available.')


if __name__ == '__main__':
    asyncio.run(check())
