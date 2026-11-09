import tempfile
import threading
import time
import unittest
from polaris_codex_cli import CodexCLI
from polaris_platform.protocol import PlatformError


class FakeTransport:
    instances = []
    def __init__(self, message, exited):
        self.message, self.exited, self.calls = message, exited, []
        FakeTransport.instances.append(self)
    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/start': return {'thread': {'id': 'thread-' + str(len([c for c in self.calls if c[0] == method]))}}
        if method == 'turn/start':
            self.message({'method': 'turn/started', 'params': {'threadId': params['threadId'], 'turn': {'id': 'turn-1'}}})
            return {'turn': {'id': 'turn-1'}}
        return {}
    def reply(self, ident, result): self.calls.append(('reply', (ident, result)))
    def close(self): self.exited()


class Context:
    def __init__(self): self.published = []; self.ready = threading.Event()
    def publish(self, event, payload): self.published.append((event, payload)); self.ready.set()


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.c = CodexCLI({'instanceId': 'instance', 'dataDir': self.temp.name}, FakeTransport)
        self.c.start(object()); self.c.configure(self.temp.name)
        self.addCleanup(self.c.stop)

    def test_send_result_event_and_steer(self):
        context = Context()
        result = self.c.send('hello', ctx=context)
        self.assertEqual(result['turnId'], 'turn-1')
        with self.assertRaises(PlatformError): self.c.send('second', ctx=context)
        self.c.send('more', mode='steer', ctx=context)
        self.c._message({'method': 'item/completed', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'item': {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'done'}}})
        self.c._message({'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'completed', 'error': None}}})
        self.assertTrue(context.ready.wait(2))
        self.assertEqual(context.published[0][1]['reply'], 'done')
        self.assertEqual(self.c.result('turn-1')['status'], 'completed')
        self.assertIsNone(self.c.get()['activeTurnId'])

    def test_new_compact_and_restart_resume(self):
        self.c.compact()
        self.c.new()
        self.c.send('first')
        self.c.stop()
        other = CodexCLI({'instanceId': 'instance', 'dataDir': self.temp.name}, FakeTransport)
        other.start(object())
        for _ in range(100):
            if other.connection == 'ready': break
            time.sleep(.01)
        self.assertEqual(other.get()['threadId'], 'thread-2')
        self.assertEqual(FakeTransport.instances[-1].calls[0][0], 'thread/resume')
        other.stop()

    def test_disconnect_does_not_fabricate_completion(self):
        context = Context(); self.c.send('hello', ctx=context)
        self.c._exited()
        self.assertEqual(self.c.result('turn-1')['status'], 'unknown')
        self.assertEqual(context.published, [])


if __name__ == '__main__': unittest.main()

class PlatformEventTests(unittest.TestCase):
    def test_subscriber_receives_finished_event(self):
        import json
        from pathlib import Path
        from polaris_platform.bootstrap import build
        from polaris_platform.component import Component
        root = Path(__file__).resolve().parents[4] / 'next'
        runtime = build(json.loads((root / 'config.headless.json').read_text()), root)
        temp = tempfile.TemporaryDirectory()
        def manifest(name): return {'id': name, 'name': name, 'version': '1', 'platformApi': 1, 'entry': {'mode': 'inprocess'}}
        try:
            runtime.install(manifest('caller'), Component); runtime.start_component('caller')
            runtime.install(manifest('codex-test'), lambda: CodexCLI({'instanceId': 'x', 'dataDir': temp.name}, FakeTransport)); runtime.start_component('codex-test')
            c = runtime.component_instance('codex-test'); c.configure(temp.name)
            for operation in ('send',): runtime.grant('caller', 'codex-test', operation)
            runtime.grant('caller', 'codex-test', 'turn.finished', kind='event')
            client = runtime.client('caller'); context = runtime.user_context('caller')
            received, done = [], threading.Event()
            def callback(payload, ctx): received.append(payload); done.set()
            client.subscribe('codex-test', 'turn.finished', callback, context=context)
            client.call('codex-test', 'send', {'text': 'hello'}, context=context)
            c._message({'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'completed'}}})
            self.assertTrue(done.wait(2)); self.assertEqual(received[0]['turnId'], 'turn-1')
        finally:
            for row in reversed(runtime.snapshot()):
                try: runtime.stop_component(row['id'], force=True)
                except Exception: pass
            temp.cleanup()
