import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polaris_agent.model import AgentStore
from polaris_agent.bridge import Bridge

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.store = AgentStore(self.path / 'agent.json')
    def tearDown(self):
        self.doCleanups()
        self.tmp.cleanup()
    def test_mark_offline_result_dedup(self):
        row = self.store.snapshot('pi', 'host', 's', canSend=True)
        self.store.mark(row['id'])
        self.store.run_event(row['id'], 'a')
        self.store.offline('pi', 'host')
        self.assertEqual(self.store.result(row['id'])['status'], 'running')
        self.store.run_event(row['id'], 'a', 'completed', 'one')
        self.store.run_event(row['id'], 'a', 'completed', 'two')
        self.assertEqual(len(self.store.notices), 1)
        self.store.run_event(row['id'], 'b')
        self.assertIsNone(self.store.result(row['id'])['reply'])
        restored = AgentStore(self.path / 'agent.json')
        self.assertTrue(restored.status(row['id'])['marked'])
        self.assertFalse(restored.status(row['id'])['online'])
    def test_bridge_delivery(self):
        bridge = Bridge(self.store, self.path / 'bridge')
        self.addCleanup(bridge.close)
        endpoint = json.loads(bridge.endpoint.read_text())
        sock = socket.create_connection((endpoint['host'], endpoint['port']))
        self.addCleanup(sock.close)
        stream = sock.makefile('rwb', buffering=0)
        def send(value):
            stream.write((json.dumps(value)+'\n').encode())
        def read():
            return json.loads(stream.readline())
        send(dict(type='hello', token=endpoint['token'], adapter='pi', clientId='h'))
        self.assertTrue(read()['ok'])
        send(dict(type='event',event='session.snapshot',sessionId='s',canSend=True))
        send(dict(type='request',requestId='mark',operation='session.mark',params={'sessionId':'s'}))
        row = read()['result']
        delivery = bridge.send(row['id'], 'hello', 'd1', 'start')
        self.assertEqual(read()['sessionId'], 's')
        self.assertEqual(delivery['status'], 'pending')
        delivery['owner'].clear()
        self.assertEqual(self.store.delivery('d1')['owner'], ['pi', 'h'])
        self.assertEqual(bridge.send(row['id'], 'hello', 'd1', 'start')['id'], 'd1')
        send(dict(type='event',event='command.result',requestId='d1',status='accepted',turnId='actual-turn'))
        send(dict(type='request',requestId='get',operation='session.delivery',params={'deliveryId':'d1'}))
        receipt = read()['result']
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(receipt['turnId'], 'actual-turn')
        self.assertEqual(self.store.result(row['id']), None)
        with self.assertRaises(ValueError):
            bridge.send(row['id'], 'different', 'd1', 'start')

    def test_connection_replacement_cannot_claim_old_delivery(self):
        bridge = Bridge(self.store, self.path / 'bridge')
        self.addCleanup(bridge.close)
        endpoint = json.loads(bridge.endpoint.read_text())
        def connect():
            sock = socket.create_connection(('127.0.0.1', endpoint['port']))
            sock.settimeout(2)
            self.addCleanup(sock.close)
            stream = sock.makefile('rwb', buffering=0)
            def send(frame):
                stream.write((json.dumps(frame)+'\n').encode())
            def read():
                return json.loads(stream.readline())
            send(dict(type='hello', token=endpoint['token'], adapter='pi', clientId='h'))
            self.assertTrue(read()['ok'])
            return send, read
        send, read = connect()
        send(dict(type='event', event='session.snapshot', sessionId='s', canSend=True))
        send(dict(type='request', requestId='m', operation='session.mark', params={'sessionId':'s'}))
        row = read()['result']
        bridge.send(row['id'], 'hello', 'old', 'start')
        read()
        send2, read2 = connect()
        send2(dict(type='event', event='command.result', requestId='old', status='accepted'))
        self.assertIn('error', read2())
        self.assertEqual(self.store.delivery('old')['status'], 'unknown')
        self.assertTrue(self.store.status(row['id'])['marked'])
        other = self.store.snapshot('pi', 'different-host', 's', canSend=True)
        self.store.mark(other['id'])
        with self.assertRaises(ValueError):
            bridge.send(other['id'], 'never wrong host', mode='start')

    def test_bridge_rejects_internal_session_key_and_expires_delivery(self):
        bridge = Bridge(self.store, self.path / 'bridge')
        bridge.delivery_timeout = .05
        self.addCleanup(bridge.close)
        endpoint = json.loads(bridge.endpoint.read_text())
        foreign = self.store.snapshot('pi', 'other', 'foreign', canSend=True)
        sock = socket.create_connection(('127.0.0.1', endpoint['port']))
        sock.settimeout(2)
        self.addCleanup(sock.close)
        stream = sock.makefile('rwb', buffering=0)
        def send(frame):
            stream.write((json.dumps(frame)+'\n').encode())
        def read():
            return json.loads(stream.readline())
        send(dict(type='hello', token=endpoint['token'], adapter='pi', clientId='h'))
        read()
        for operation in ('session.mark', 'session.unmark', 'session.status', 'session.reply', 'session.send'):
            send(dict(type='request', requestId=operation, operation=operation,
                      params={'session_id': foreign['id'], 'text':'wrong'}))
            self.assertIn('error', read())
        self.assertFalse(self.store.status(foreign['id'])['marked'])
        send(dict(type='event', event='session.snapshot', sessionId='s', canSend=True))
        send(dict(type='request', requestId='m', operation='session.mark', params={'sessionId':'s'}))
        row = read()['result']
        bridge.send(row['id'], 'hello', 'timeout', 'steer')
        self.assertEqual(read()['mode'], 'steer')
        deadline = time.time() + 2
        while self.store.delivery('timeout')['status'] == 'pending' and time.time() < deadline:
            time.sleep(.02)
        self.assertEqual(self.store.delivery('timeout')['status'], 'unknown')
        self.assertEqual(bridge.send(row['id'], 'hello', 'timeout', 'steer')['status'], 'unknown')

    def test_bridge_exclusive_endpoint_and_symlink(self):
        bridge = Bridge(self.store, self.path / 'bridge')
        self.addCleanup(bridge.close)
        original = bridge.endpoint.read_text()
        with self.assertRaises(ValueError):
            Bridge(self.store, self.path / 'bridge')
        self.assertEqual(bridge.endpoint.read_text(), original)
        bridge.close()
        target = self.path / 'untouched'
        target.write_text('private')
        bridge.endpoint.symlink_to(target)
        replacement = Bridge(self.store, self.path / 'bridge')
        self.addCleanup(replacement.close)
        self.assertEqual(target.read_text(), 'private')
        self.assertFalse(replacement.endpoint.is_symlink())

    def test_failed_save_rolls_back_and_public_records_are_copies(self):
        from unittest.mock import patch
        row = self.store.snapshot('pi', 'h', 's', canSend=True)
        self.store.run_event(row['id'], 'r')
        before = (self.path / 'agent.json').read_bytes()
        with patch.object(self.store, 'save', side_effect=OSError('disk unavailable')):
            with self.assertRaises(ValueError):
                self.store.mark(row['id'])
            with self.assertRaises(ValueError):
                self.store.run_event(row['id'], 'r', 'completed', 'must rollback', reply_truncated=True)
        self.assertEqual((self.path / 'agent.json').read_bytes(), before)
        self.assertFalse(self.store.status(row['id'])['marked'])
        self.assertEqual(self.store.result(row['id'])['status'], 'running')
        self.assertEqual(self.store.notices, [])
        returned = self.store.mark(row['id'])
        returned['runs'].clear()
        self.assertEqual(len(self.store.status(row['id'])['runs']), 1)
        self.store.deliveries['d'] = {'id':'d', 'status':'accepted', 'owner':['pi','h']}
        returned = self.store.delivery('d')
        returned['owner'].clear()
        self.assertEqual(self.store.delivery('d')['owner'], ['pi','h'])
        run = self.store.run_event(row['id'], 'r', 'completed', 'partial', reply_truncated=True)
        self.assertTrue(run['replyTruncated'])

    def test_unknown_updates_reply_without_repeating_notice(self):
        row = self.store.snapshot('codex', 'host', 's', canSend=True)
        self.store.mark(row['id'])
        first = self.store.run_event(row['id'], 'turn', 'unknown', 'first', reply_truncated=True)
        self.store.run_event(row['id'], 'turn', 'unknown', 'continued', reply_truncated=False)
        updated = self.store.result(row['id'], 'turn')
        self.assertEqual(updated['reply'], 'continued')
        self.assertFalse(updated['replyTruncated'])
        self.assertEqual(updated['startedAt'], first['startedAt'])
        self.assertEqual(updated['endedAt'], first['endedAt'])
        self.assertEqual(len(self.store.notices), 1)
        self.store.run_event(row['id'], 'turn', 'completed', 'settled')
        self.store.run_event(row['id'], 'turn', 'unknown', 'stale')
        self.assertEqual(self.store.result(row['id'])['reply'], 'settled')
        self.assertEqual(len(self.store.notices), 1)
