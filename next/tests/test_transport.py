import json
import sys
import tempfile
import os
import threading
import unittest
from pathlib import Path
from polaris_platform.transport import ProcessComponent, _Peer, MAX_REQUESTS
from polaris_platform.protocol import PlatformError

ROOT = Path(__file__).resolve().parents[1]

class TransportTests(unittest.TestCase):
    def provider(self, name='notes', timeout=2):
        directory = ROOT / 'examples' / name
        return ProcessComponent(json.loads((directory / 'manifest.json').read_text()), directory, timeout)

    def test_real_process(self):
        provider = self.provider()
        try:
            self.assertIn('create', provider.describe()['operations'])
            provider.start(None)
            result = provider.call('create', {'title': 'Hello'}, object())
            self.assertEqual(provider.call('get', {'id': result['id']}, object())['title'], 'Hello')
        finally:
            provider.stop()
        self.assertIsNone(provider.process)

    def test_nested_context_and_denial(self):
        provider = self.provider('labeler')
        context = object()
        class Port:
            def call(inner, target, operation, params, context=None):
                self.assertIs(context, expected)
                raise PlatformError('denied', 'not granted')
        expected = context
        try:
            provider.start(Port())
            with self.assertRaises(PlatformError) as caught:
                provider.call('label', {'note_id': '1'}, context)
            self.assertEqual(caught.exception.code, 'denied')
            with self.assertRaises(PlatformError):
                provider._reverse('call', {'token': 'invented', 'target': 'notes'})
        finally:
            provider.stop()

    def test_frame_limit_and_cycle_fail_without_waiting_for_timeout(self):
        provider = self.provider('labeler')
        context = object()
        class Port:
            def call(inner, target, operation, params, context=None):
                return provider.call('label', {'note_id': '1'}, context)
        try:
            provider.start(Port())
            with self.assertRaises(PlatformError) as oversized:
                provider.call('get', {'note_id': 'x' * (1024 * 1024)}, context)
            self.assertEqual(oversized.exception.code, 'frame_too_large')
            with self.assertRaises(PlatformError) as cycle:
                provider.call('label', {'note_id': '1'}, context)
            self.assertEqual(cycle.exception.code, 'call_cycle')
            self.assertFalse(provider.call_failed)
        finally:
            provider.stop()

    def test_frame_limit_counts_final_newline_consistently(self):
        from io import StringIO
        from polaris_platform.transport import MAX_FRAME_BYTES
        # This isolated writer verifies the exact boundary without starting a reader.
        peer = _Peer.__new__(_Peer)
        peer.lock = threading.RLock()
        peer.closed = False
        peer.writer = StringIO()
        message = {'result': ''}
        overhead = len(json.dumps(message, ensure_ascii=False).encode('utf-8')) + 1
        message['result'] = 'x' * (MAX_FRAME_BYTES - overhead)
        peer._send(message)
        self.assertEqual(len(peer.writer.getvalue().encode('utf-8')), MAX_FRAME_BYTES)
        message['result'] += 'x'
        with self.assertRaises(PlatformError) as caught:
            peer._send(message)
        self.assertEqual(caught.exception.code, 'frame_too_large')

    def test_inbound_worker_limit_is_bounded(self):
        input_read, input_write = os.pipe()
        output_read, output_write = os.pipe()
        reader, remote = os.fdopen(input_read), os.fdopen(input_write, 'w')
        incoming, writer = os.fdopen(output_read), os.fdopen(output_write, 'w')
        release = threading.Event()
        def handler(method, params):
            release.wait(3)
            return None
        peer = _Peer(reader, writer, handler)
        try:
            for number in range(MAX_REQUESTS + 1):
                remote.write(json.dumps({'id': str(number), 'method': 'wait', 'params': {}}) + '\n')
            remote.flush()
            response = json.loads(incoming.readline())
            self.assertEqual(response['error']['code'], 'busy')
            self.assertEqual(response['id'], str(MAX_REQUESTS))
            self.assertEqual(len(peer.workers), MAX_REQUESTS)
        finally:
            release.set()
            remote.close()
            peer.thread.join(timeout=3)
            for worker in list(peer.workers):
                worker.join(timeout=3)
            peer.close()
            reader.close()
            writer.close()
            incoming.close()


    def test_timeout_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'child.py'
            path.write_text('from polaris_platform.sdk import Component\nimport time\nc=Component()\n@c.operation("slow", access="write")\ndef slow(): time.sleep(2)\nc.run()\n')
            provider = ProcessComponent({'entry': {'command': [sys.executable, str(path)]}}, directory, .2)
            try:
                provider.start(None)
                with self.assertRaises(PlatformError) as caught:
                    provider.call('slow', {}, object())
                self.assertEqual(caught.exception.code, 'timeout')
                self.assertFalse(provider.tokens)
                with self.assertRaises(PlatformError) as blocked:
                    provider.call('slow', {}, object())
                self.assertEqual(blocked.exception.code, 'unavailable')
                provider.process.kill()
                provider.process.wait()
                with self.assertRaises(PlatformError):
                    provider.peer.request('describe')
            finally:
                provider.force_stop()
