"""Dependency-free MCP stdio client for the running Polaris component."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

MAX_FRAME = 1024 * 1024


def default_endpoint():
    root = os.environ.get('LOCALAPPDATA') if os.name == 'nt' else os.environ.get('XDG_DATA_HOME')
    state = (Path(root) if root else Path.home() / '.local/share') / 'polaris-platform'
    records = json.loads((state / 'installations.json').read_text(encoding='utf-8'))
    record = next(row for row in records if row['manifest']['id'] == 'mcp')
    return state / 'components' / record['installationId'] / 'endpoint.json'


def forward(message, endpoint):
    config = json.loads(Path(endpoint).read_text(encoding='utf-8'))
    if config.get('version') != 1 or config.get('host') != '127.0.0.1':
        raise ValueError('Invalid Polaris MCP endpoint')
    payload = json.dumps({'token': config['token'], 'message': message}, ensure_ascii=False, allow_nan=False).encode() + b'\n'
    if len(payload) > MAX_FRAME:
        raise ValueError('MCP request exceeds 1 MiB')
    with socket.create_connection(('127.0.0.1', config['port']), timeout=5) as connection:
        connection.settimeout(310)
        connection.sendall(payload)
        with connection.makefile('rb') as stream:
            raw = stream.readline(MAX_FRAME + 1)
        if len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
            raise ValueError('Polaris MCP disconnected or returned an oversized response')
        return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', type=Path)
    args = parser.parse_args()
    endpoint = args.endpoint
    for raw in sys.stdin.buffer:
        message = None
        try:
            if len(raw) > MAX_FRAME:
                raise ValueError('MCP request exceeds 1 MiB')
            message = json.loads(raw)
            response = forward(message, endpoint or default_endpoint())
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            # Never retry a request: a write may have already executed.
            if isinstance(message, dict) and 'id' not in message:
                continue
            response = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                        'error': {'code': -32603 if message is not None else -32700,
                                  'message': 'Polaris MCP unavailable: ' + str(exc)}}
        if response is not None:
            sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode() + b'\n')
            sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
