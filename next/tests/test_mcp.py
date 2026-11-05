"""Exercise the real runtime, authenticated socket and spawned MCP stdio client."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

from components import manifest
from components.mcp import MCP
from components.mcp.stdio import forward
from polaris_platform.bootstrap import build, default_config
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rt = build(default_config(), state_dir=Path(self.temp.name) / 'platform')
        self.addCleanup(self.stop)
        self.calls = []
        self.toy = Component()
        self.toy.operation('read')(lambda p, c: {'value': len(self.calls)})
        self.toy.operation('write', access='write')(lambda p, c: self.calls.append(p['value']) or {'saved': p['value']})
        self.toy.operation('fail', access='write')(self.fail_after_write)
        self.toy.operation('nested')(lambda p, c: self.toy.port.call('other', 'read', {}, context=c))
        self.toy.operation('secret')(lambda p, c: 'hidden')
        self.toy._operations['secret']['humanOnly'] = True
        self.toy.operation('native')(lambda p, c: object())
        self.toy._operations['native']['profile'] = 'qt-native'
        self.toy.event('changed')
        self.add('toy', self.toy)
        other = Component()
        other.operation('read')(lambda p, c: {'nested': True})
        self.add('other', other)
        self.mcp = MCP(self.rt)
        self.rt.install(manifest('mcp'), lambda: self.mcp, trusted_bindings=True)
        self.rt.start_component('mcp')
        self.endpoint = self.mcp.directory / 'endpoint.json'

    def add(self, identity, component):
        self.rt.install({'id': identity, 'name': identity, 'version': '1', 'platformApi': 1,
                         'entry': {'mode': 'inprocess'}}, lambda: component)
        self.rt.start_component(identity)

    def stop(self):
        for row in reversed(self.rt.snapshot()):
            if row['state'] == 'running':
                self.rt.stop_component(row['id'], persist=False)

    def fail_after_write(self, params, context):
        self.calls.append('attempted')
        raise RuntimeError('result unknown')

    def rpc(self, method, params=None):
        return forward({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}, self.endpoint)

    def tool(self, name, arguments=None):
        result = self.rpc('tools/call', {'name': name, 'arguments': arguments or {}})['result']
        return result['isError'], json.loads(result['content'][0]['text'])

    def call(self, operation, **arguments):
        return self.tool('polaris_call', {'component': 'toy', 'operation': operation, 'arguments': arguments})

    def test_real_stdio_handshake_catalog_and_write(self):
        frames = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'polaris_call', 'arguments': {
                'component': 'toy', 'operation': 'write', 'arguments': {'value': '中文'}}}},
        ]
        script = Path(__file__).parents[1] / 'components/mcp/stdio.py'
        result = subprocess.run([sys.executable, str(script), '--endpoint', str(self.endpoint)],
                                input=''.join(json.dumps(frame) + '\n' for frame in frames),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies], [1, 2, 3])
        self.assertEqual(replies[0]['result']['protocolVersion'], '2025-11-25')
        self.assertEqual(len(replies[1]['result']['tools']), 3)
        self.assertFalse(replies[2]['result']['isError'])
        self.assertEqual(self.calls, ['中文'])
        self.assertEqual(self.call('nested'), (False, {'nested': True}))

    def test_revocation_survives_service_and_process_restart(self):
        self.assertFalse(self.call('write', value=1)[0])
        self.rt.revoke('mcp', 'toy', 'write', background=True)
        self.assertTrue(self.call('write', value=2)[0])
        self.rt.stop_component('mcp', persist=False)
        self.rt.start_component('mcp')
        self.assertTrue(self.call('write', value=3)[0])
        self.assertEqual(self.calls, [1])
        # A fresh component object restores the same decisions from disk.
        self.rt.stop_component('mcp', persist=False)
        replacement = MCP(self.rt)
        self.rt.replace_component('mcp', manifest('mcp'), lambda: replacement)
        self.rt.start_component('mcp')
        self.mcp = replacement
        self.assertTrue(self.call('write', value=4)[0])
        self.rt.grant('mcp', 'toy', 'write', background=True)
        self.assertFalse(self.call('write', value=5)[0])

    def test_dynamic_capabilities_stop_and_live_scope(self):
        self.assertFalse(self.call('read')[0])
        self.toy.operation('new', access='write')(lambda p, c: 'new')
        self.assertEqual(self.call('new'), (False, 'new'))
        self.toy.withdraw_operation('new')
        self.assertTrue(self.call('new')[0])
        self.rt.stop_component('toy')
        self.assertTrue(self.call('read')[0])
        self.rt.start_component('toy')
        self.assertFalse(self.call('read')[0])
        catalog, context = self.mcp.catalog()
        self.assertIn('changed', [key[2] for key in context.scope if key[1] == 'event'])
        self.rt.revoke('mcp', 'toy', 'read', background=True)
        with self.assertRaises(PlatformError):
            self.mcp.port.call('toy', 'read', {}, context=context)

    def test_hidden_operations_and_default_off(self):
        _, listing = self.tool('polaris_components')
        toy = next(r for r in listing['components'] if r['id'] == 'toy')
        self.assertNotIn('secret', toy['operations'])
        self.assertNotIn('native', toy['operations'])
        self.assertTrue(self.call('secret')[0])
        self.assertTrue(self.call('native')[0])
        self.mcp.default_all = False
        self.toy.operation('ungranted')(lambda p, c: True)
        self.assertTrue(self.call('ungranted')[0])

    def test_authentication_protocol_errors_and_no_write_retry(self):
        config = json.loads(self.endpoint.read_text())
        with socket.create_connection((config['host'], config['port']), timeout=2) as connection:
            connection.sendall((json.dumps({'token': 'wrong', 'message': {'id': 1}}) + '\n').encode())
            self.assertEqual(connection.recv(1024), b'')
        self.assertEqual(self.rpc('unknown')['error']['code'], -32601)
        self.assertEqual(self.rpc('tools/call', {'name': 'missing'})['error']['code'], -32602)
        self.assertTrue(self.call('fail')[0])
        self.assertEqual(self.calls, ['attempted'])
        self.rt.stop_component('mcp', persist=False)
        self.assertFalse(self.endpoint.exists())
        with self.assertRaises(OSError):
            self.rpc('ping')

    def test_second_owner_cannot_delete_live_endpoint(self):
        duplicate = MCP(self.rt, data_dir=self.mcp.directory)
        with self.assertRaises(OSError):
            duplicate.start(self.rt.client('mcp'))
        duplicate.stop()
        self.assertEqual(self.rpc('ping')['result'], {})


if __name__ == '__main__':
    unittest.main()
