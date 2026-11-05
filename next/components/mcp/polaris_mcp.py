"""Trusted MCP input boundary with persistent, revocable default grants."""
import hmac
import json
import os
from pathlib import Path
import secrets
import socketserver
import tempfile
from threading import RLock, Thread

from polaris_platform.component import Component
from polaris_platform.persistence import read_json, write_json
from polaris_platform.protocol import PlatformError, capability

MAX_FRAME = 1024 * 1024
VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')


def callable_operations(record):
    return {name: meta for name, meta in record.get('description', {}).get('operations', {}).items()
            if meta.get('available', True) and meta.get('profile') != 'qt-native'
            and not meta.get('humanOnly') and meta.get('modelCallable') is not False}


TOOLS = [
    {'name': 'polaris_components', 'description': '列出北极星当前已授权、可调用的组件和操作。',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': True}},
    {'name': 'polaris_help', 'description': '查询组件公开操作的参数、说明和读写类型，调用前先查询。',
     'inputSchema': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'operation': {'type': 'string'}},
                     'required': ['component'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': True}},
    {'name': 'polaris_call', 'description': '调用北极星组件公开操作。先用 polaris_help 查询参数。写操作可能改变数据；结果未知时先查询实际状态，不要盲目重试。',
     'inputSchema': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'operation': {'type': 'string'},
                                                   'arguments': {'type': 'object'}},
                     'required': ['component', 'operation'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False}},
]


class MCP(Component):
    def __init__(self, runtime, data_dir=None, default_all=True):
        super().__init__()
        self.runtime = runtime
        self.directory = Path(data_dir) if data_dir else None
        self._temporary = None
        self.default_all = default_all
        self._lock = RLock()
        self._server = self._thread = None
        self._seen = set()
        self._token = None
        self.operation('status')(lambda p, c: {'running': self._server is not None,
                                               'defaultAllPermissions': self.default_all,
                                               'transport': 'stdio', 'endpointFile': str(self.directory / 'endpoint.json')})

    def start(self, port):
        super().start(port)
        if self.directory is None:
            self.directory = self.runtime.component_data_directory(port.id)
            if self.directory is None:
                self._temporary = tempfile.TemporaryDirectory(prefix='polaris-mcp-')
                self.directory = Path(self._temporary.name)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        state = read_json(self.directory / 'defaults.json', {'version': 1, 'seen': []})
        if state.get('version') != 1 or not isinstance(state.get('seen'), list):
            raise ValueError('Invalid MCP permission defaults file')
        self._seen = {tuple(key) for key in state['seen']}
        # One live owner per endpoint; stale endpoints are replaced after a crash.
        self._ownership = open(self.directory / 'owner.lock', 'a+b')
        if os.name == 'nt':
            import msvcrt
            self._ownership.seek(0)
            self._ownership.write(b'0')
            self._ownership.flush()
            self._ownership.seek(0)
            msvcrt.locking(self._ownership.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(310)
                try:
                    raw = self.rfile.readline(MAX_FRAME + 1)
                    if len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
                        return
                    envelope = json.loads(raw)
                    token = envelope.get('token')
                    if not isinstance(token, str) or not hmac.compare_digest(token, owner._token):
                        return
                    response = owner.request(envelope.get('message'))
                    payload = json.dumps(response, ensure_ascii=False, allow_nan=False).encode() + b'\n'
                    if len(payload) > MAX_FRAME:
                        message = envelope.get('message') or {}
                        payload = json.dumps({'jsonrpc': '2.0', 'id': message.get('id'),
                                              'error': {'code': -32603, 'message': 'MCP result exceeds 1 MiB; query a smaller range'}}).encode() + b'\n'
                    self.wfile.write(payload)
                except (ValueError, OSError, TypeError):
                    return

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            block_on_close = False

        self._token = secrets.token_hex(32)
        self._server = Server(('127.0.0.1', 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        self._thread.start()
        write_json(self.directory / 'endpoint.json', {'version': 1, 'host': '127.0.0.1',
                   'port': self._server.server_address[1], 'token': self._token})
        (self.directory / 'endpoint.json').chmod(0o600)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)
            self._server = self._thread = None
        if self.directory is not None:
            endpoint = self.directory / 'endpoint.json'
            if self._token and endpoint.exists() and read_json(endpoint, {}).get('token') == self._token:
                endpoint.unlink()
        self._token = None
        ownership = getattr(self, '_ownership', None)
        if ownership:
            ownership.close()
            self._ownership = None
        super().stop()
        if self._temporary:
            self._temporary.cleanup()
            self._temporary = None
            self.directory = None

    def catalog(self):
        """Grant new capability identities once; never restore a revoked grant."""
        with self._lock:
            if not self.port or self._server is None:
                raise PlatformError('unavailable', 'MCP component is stopped')
            self.runtime.validate_client(self.port)
            records = self.runtime.collaboration.discover()['components']
            subject = self.port.id
            installation = self.runtime.status(subject)['installation']
            candidates = []
            for record in records:
                if record['id'] == subject:
                    continue
                for kind, entries in (('operation', callable_operations(record)),
                                      ('event', record.get('description', {}).get('events', {}))):
                    for name, meta in entries.items():
                        key = capability(record['installation'], kind, name, meta)
                        marker = (installation, *key)
                        if marker not in self._seen and self.default_all:
                            # Persist before granting: a crash must not restore
                            # a previously revoked permission on the next start.
                            self._seen.add(marker)
                            write_json(self.directory / 'defaults.json', {'version': 1, 'seen': [list(k) for k in sorted(self._seen)]})
                            self.runtime.grant(subject, record['id'], name, kind=kind, background=True, expected_key=key)
                        if kind == 'operation':
                            candidates.append((record, name, meta, key))
            context = self.runtime.background_context(subject)
            catalog = {}
            for record, name, meta, key in candidates:
                if key in context.scope:
                    entry = catalog.setdefault(record['id'], {'id': record['id'], 'name': record['manifest']['name'], 'operations': {}})
                    entry['operations'][name] = meta
            return catalog, context

    def execute(self, name, arguments):
        catalog, context = self.catalog()
        if name == 'polaris_components':
            if arguments:
                raise PlatformError('invalid_params', '此工具不接受参数')
            return {'components': list(catalog.values())}
        target = arguments.get('component')
        if not isinstance(target, str) or target not in catalog:
            raise PlatformError('permission_required', '组件不可用或未授权，请查询 polaris_components')
        entry = catalog[target]
        operation = arguments.get('operation')
        if name == 'polaris_help':
            if set(arguments) - {'component', 'operation'}:
                raise PlatformError('invalid_params', '未知参数')
            if operation is None:
                return entry
            if not isinstance(operation, str) or operation not in entry['operations']:
                raise PlatformError('permission_required', '操作不可用或未授权')
            return {**entry, 'operations': {operation: entry['operations'][operation]}}
        if name != 'polaris_call':
            raise PlatformError('invalid_params', '未知工具')
        if set(arguments) - {'component', 'operation', 'arguments'}:
            raise PlatformError('invalid_params', '未知参数')
        if not isinstance(operation, str) or operation not in entry['operations']:
            raise PlatformError('permission_required', '操作不可用或未授权')
        params = arguments.get('arguments', {})
        if not isinstance(params, dict):
            raise PlatformError('invalid_params', 'arguments 必须为对象')
        # Ordinary Client dispatch checks live grants, installation and instance.
        result = self.port.call(target, operation, params, context=context)
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result

    def request(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}
        if 'id' not in message:
            return None
        identity = message['id']
        method, params = message['method'], message.get('params', {})
        def error(code, text):
            return {'jsonrpc': '2.0', 'id': identity, 'error': {'code': code, 'message': text}}
        if not isinstance(params, dict):
            return error(-32602, 'params must be an object')
        if method == 'initialize':
            offered = params.get('protocolVersion')
            result = {'protocolVersion': offered if offered in VERSIONS else VERSIONS[0],
                      'capabilities': {'tools': {}}, 'serverInfo': {'name': 'polaris', 'version': '0.1.0'},
                      'instructions': '使用 polaris_components 查找组件，再用 polaris_help 查询操作参数。调用受北极星当前授权约束。'}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            if params.get('name') not in {tool['name'] for tool in TOOLS}:
                return error(-32602, 'Unknown tool')
            arguments = params.get('arguments', {})
            if not isinstance(arguments, dict):
                return error(-32602, 'arguments must be an object')
            try:
                output = self.execute(params['name'], arguments)
                result = {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False, allow_nan=False)}], 'isError': False}
            except PlatformError as exc:
                result = {'content': [{'type': 'text', 'text': json.dumps(exc.as_dict(), ensure_ascii=False)}], 'isError': True}
            except Exception as exc:
                result = {'content': [{'type': 'text', 'text': json.dumps({'code': 'component_error', 'message': str(exc)}, ensure_ascii=False)}], 'isError': True}
        else:
            return error(-32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': identity, 'result': result}


def create(runtime, data_dir=None, default_all=True):
    return MCP(runtime, data_dir, default_all)
