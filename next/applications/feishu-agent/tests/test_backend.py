"""Offline channel tests. No real Codex invocation or Feishu message is sent."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('feishu_agent_backend', Path(__file__).parents[1] / 'backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class Rejection(Exception):
    code = 'permission_denied'


def message(index, text='hello', chat='chat', thread='', direction='inbound'):
    return dict(messageId='m' + str(index), chatId=chat, text=text, direction=direction,
                messageType='text', normalized=dict(conversation=dict(thread_id=thread)))


class Context:
    def __init__(self, directory):
        self.data_directory = directory
        self.application_id = 'app_fixture'
        self.stopped = threading.Event()
        self.bindings = {name: dict(instanceId='codex' if name.startswith('codex') else 'feishu')
                         for name in ('codexGet', 'codexSend', 'feishuRead', 'feishuReply')}
        self.messages = []
        self.calls = []
        self.published = {}
        self.fail = {}
        self.codex = dict(cwd='/work/project', threadId='existing-session', connection='ready', activeTurnId=None, turns=[])
        self.serial = 0

    def publish(self, state):
        self.published = deepcopy(state)

    def call(self, alias, params):
        self.calls.append((alias, deepcopy(params)))
        if alias in self.fail:
            raise self.fail[alias]
        if alias == 'codexGet':
            return deepcopy(self.codex)
        if alias == 'feishuRead':
            items = self.messages[params['after']:params['after'] + params['limit']]
            return dict(items=deepcopy(items), nextCursor=params['after'] + len(items))
        if alias == 'codexSend':
            if params['mode'] == 'start':
                self.serial += 1
                self.codex['activeTurnId'] = 'turn-' + str(self.serial)
                self.codex['turns'].append(dict(turnId=self.codex['activeTurnId'], threadId=self.codex['threadId'], status='running', reply=None, error=None))
            return dict(threadId=self.codex['threadId'], turnId=self.codex['activeTurnId'])
        if alias == 'feishuReply':
            return dict(messageId='sent-' + str(len(self.calls)))
        raise AssertionError('Unexpected capability: ' + alias)

    def finish(self, reply='Codex answer', status='completed'):
        turn = self.codex['turns'][-1]
        turn.update(status=status, reply=reply)
        self.codex['activeTurnId'] = None


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = Context(Path(self.temp.name))
        self.service = backend.create(self.context)
        self.service.running = True
        self.tick()

    def tearDown(self):
        self.context.stopped.set()
        self.service.stop()
        self.temp.cleanup()

    def tick(self):
        self.service._poll_codex()
        self.service._receive()
        self.service._submit()
        self.service._flush()
        self.service._publish()

    def receive(self, text='hello', **kwargs):
        self.context.messages.append(message(len(self.context.messages) + 1, text, **kwargs))
        self.tick()

    def output(self, **changes):
        result = dict(deliveryId='delivery', sessionId='bridge-session', runId='run', status='completed', reply='Bridge answer')
        result.update(changes)
        return self.service.handle('bridge_output', dict(result=result))

    def test_existing_session_only_receives_new_messages_never_replayed_history(self):
        self.receive('first')
        self.context.finish()
        self.tick()
        self.receive('second')
        sent = [params for alias, params in self.context.calls if alias == 'codexSend']
        self.assertEqual(sent, [dict(text='first', mode='start'), dict(text='second', mode='start')])
        self.assertTrue(all(row['threadId'] == 'existing-session' for row in self.service.data['inputs']))
        self.assertFalse(any('agent' in alias.lower() or 'new' in alias.lower() for alias, params in self.context.calls))

    def test_running_turn_receives_only_incremental_steer(self):
        self.receive('first')
        self.receive('extra context')
        self.assertEqual([params for alias, params in self.context.calls if alias == 'codexSend'][-1], dict(text='extra context', mode='steer'))
        self.assertEqual(self.service.data['inputs'][0]['turnId'], self.service.data['inputs'][1]['turnId'])

    def test_codex_output_goes_to_feishu_once_and_is_not_model_input(self):
        self.receive()
        self.context.finish('full result')
        self.tick()
        self.tick()
        replies = [params for alias, params in self.context.calls if alias == 'feishuReply']
        self.assertEqual(replies, [dict(message_id='m1', text='full result', reply_in_thread=False)])
        self.assertEqual(len([1 for alias, params in self.context.calls if alias == 'codexSend']), 1)

    def test_bridge_callback_accepts_durable_output_and_never_sends_to_codex(self):
        self.receive()
        before = len([1 for alias, params in self.context.calls if alias == 'codexSend'])
        self.assertEqual(self.output(), dict(accepted=True))
        self.assertEqual(self.output(), dict(accepted=True))
        self.tick()
        self.assertEqual(len(self.service.data['outputs']), 1)
        self.assertEqual(self.service.data['outputs'][0]['state'], 'sent')
        self.assertEqual(len([1 for alias, params in self.context.calls if alias == 'codexSend']), before)
        with self.assertRaises(ValueError):
            self.output(reply='different content')

    def test_callback_before_first_message_waits_without_losing_output(self):
        self.output()
        self.tick()
        self.assertEqual(self.service.data['outputs'][0]['state'], 'queued')
        self.receive()
        self.assertEqual(self.service.data['outputs'][0]['state'], 'sent')

    def test_unknown_output_is_not_automatically_resent(self):
        self.receive()
        self.context.fail['feishuReply'] = TimeoutError('unknown dispatch')
        self.output()
        self.tick()
        row = self.service.data['outputs'][0]
        self.assertEqual(row['state'], 'unknown')
        self.tick()
        self.assertEqual(len([1 for alias, params in self.context.calls if alias == 'feishuReply']), 1)
        self.context.fail.clear()
        self.service.handle('retry', dict(kind='outputs', id=row['id']))
        self.tick()
        self.assertEqual(row['state'], 'sent')

    def test_rejected_codex_input_preserved_and_manual_retry_uses_same_text(self):
        self.context.fail['codexSend'] = Rejection('not authorized')
        self.receive('original')
        row = self.service.data['inputs'][0]
        self.assertEqual(row['state'], 'failed')
        self.assertTrue(self.service.running)
        self.context.fail.clear()
        self.service.handle('retry', dict(kind='inputs', id=row['id']))
        self.tick()
        self.assertEqual(row['state'], 'submitted')
        self.assertEqual(row['text'], 'original')

    def test_failed_read_does_not_block_bridge_output(self):
        self.receive()
        self.context.fail['feishuRead'] = Rejection('read denied')
        self.service._step('receive', self.service._receive)
        self.assertIn('receive', self.service.paused)
        self.output()
        self.service._step('output', self.service._flush)
        self.assertEqual(self.service.data['outputs'][0]['state'], 'sent')
        self.assertTrue(self.service.running)

    def test_no_echo_and_no_cross_chat_context_leak(self):
        self.receive(thread='topic')
        self.receive('outbound echo', direction='outbound')
        self.receive('another chat', chat='other')
        self.assertEqual(len([1 for alias, params in self.context.calls if alias == 'codexSend']), 1)
        self.assertEqual(self.service.data['inputs'][-1]['state'], 'failed')
        self.context.finish()
        self.tick()
        self.assertTrue([params for alias, params in self.context.calls if alias == 'feishuReply'][0]['reply_in_thread'])

    def test_restart_keeps_accepted_inputs_and_pending_outputs_without_replay(self):
        self.receive()
        self.output()
        self.context.stopped.set()
        self.service.stop()
        context = Context(self.context.data_directory)
        context.messages = deepcopy(self.context.messages)
        context.codex = deepcopy(self.context.codex)
        service = backend.create(context)
        service.running = True
        try:
            service._poll_codex()
            service._receive()
            service._submit()
            service._flush()
            self.assertFalse(any(alias == 'codexSend' for alias, params in context.calls))
            self.assertEqual(service.data['outputs'][0]['state'], 'sent')
        finally:
            context.stopped.set()
            service.stop()

    def test_legacy_state_is_retained_and_only_transferred_by_user(self):
        legacy = dict(cursor=0, conversations={'chat': 'old-conversation'}, tasks=[dict(id='old', state='failed', text='old question',
                      error='agentReply', chatId='chat', threadId='', messageId='old-message', answer='')])
        self.service.path.write_text(json.dumps(legacy))
        service = backend.create(self.context)
        self.assertEqual(service.data['legacy'], legacy)
        self.assertEqual(service.data['inputs'], [])
        self.assertEqual(service._attention()[0]['kind'], 'legacy')
        service.handle('transfer', dict(kind='legacy', id='old'))
        self.assertEqual(service.data['inputs'][0]['text'], 'old question')
        self.assertTrue(service.data['legacy']['tasks'][0]['migratedTo'])
        with self.assertRaises(ValueError):
            service.handle('transfer', dict(kind='legacy', id='old'))

    def test_first_install_skips_existing_feishu_and_codex_history(self):
        self.service.path.unlink()
        self.context.messages = [message(i) for i in range(1101)]
        self.context.codex['turns'] = [dict(turnId='old', status='completed', reply='old output')]
        service = backend.create(self.context)
        service.running = True
        try:
            service._poll_codex()
            service._receive()
            self.assertEqual(service.data['cursor'], 1101)
            self.assertEqual(service.data['inputs'], [])
            self.assertEqual(service.data['outputs'], [])
        finally:
            service.stop()

    def test_background_service_survives_capability_failure(self):
        self.context.fail['codexGet'] = Rejection('missing capability')
        self.service.running = False
        self.service.interval = .01
        self.service.start()
        until = time.monotonic() + 2
        while not self.context.published.get('issues') and time.monotonic() < until:
            time.sleep(.005)
        self.assertTrue(self.service.thread.is_alive())
        self.assertTrue(self.service.running)
        self.assertIn('missing capability', self.context.published['issues'])
        self.context.fail.clear()
        self.service.handle('continue', {})

    def test_callback_boundary_rejects_invalid_payload(self):
        for result in (None, {}, dict(deliveryId=1), dict(deliveryId='d', sessionId='s', runId='r', status='running')):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.service.handle('bridge_output', dict(result=result))

    def test_native_codex_component_reuses_thread_and_compacts_without_replaying(self):
        import sys
        root = Path(__file__).resolve().parents[4] / 'marketplace/packages/codex-cli'
        native_spec = importlib.util.spec_from_file_location('_native_codex_channel_test',
            root / 'polaris_codex_cli/__init__.py', submodule_search_locations=[str(root / 'polaris_codex_cli')])
        native_module = importlib.util.module_from_spec(native_spec)
        sys.modules[native_spec.name] = native_module
        self.addCleanup(lambda: [sys.modules.pop(key, None) for key in list(sys.modules)
                                 if key == native_spec.name or key.startswith(native_spec.name + '.')])
        native_spec.loader.exec_module(native_module)
        transport_spec = importlib.util.spec_from_file_location('_codex_transport_fixture', root / 'tests/test_component.py')
        fixture = importlib.util.module_from_spec(transport_spec)
        # Its fixture imports the public package name; use the same loaded implementation.
        with patch.dict(sys.modules, {'polaris_codex_cli': native_module}):
            transport_spec.loader.exec_module(fixture)
        native = native_module.CodexCLI(dict(instanceId='cli', dataDir=str(Path(self.temp.name) / 'native')), fixture.FakeTransport)
        native.start(object())
        native.configure(self.temp.name)
        original = self.context.call
        def call(alias, params):
            if alias == 'codexGet': return native.get()
            if alias == 'codexSend': return native.send(**params)
            return original(alias, params)
        self.context.call = call
        try:
            self.service.data['seenCodex'] = None
            self.tick()
            self.receive('first')
            self.receive('increment')
            methods = [method for method, params in native.transport.calls]
            self.assertEqual(methods.count('thread/start'), 1)
            self.assertEqual(methods.count('turn/start'), 1)
            self.assertEqual(methods.count('turn/steer'), 1)
            native._message(dict(method='item/completed', params=dict(threadId='thread-1', turnId='turn-1',
                            item=dict(type='agentMessage', text='native output'))))
            native._message(dict(method='turn/completed', params=dict(threadId='thread-1', turn=dict(id='turn-1', status='completed'))))
            self.tick()
            self.assertEqual([params['text'] for alias, params in self.context.calls if alias == 'feishuReply'], ['native output'])
            self.receive('/compact')
            self.assertEqual(native.get()['threadId'], 'thread-1')
            self.assertEqual([method for method, params in native.transport.calls].count('thread/start'), 1)
            self.assertIn('thread/compact/start', [method for method, params in native.transport.calls])
        finally:
            native.stop()

    def test_manifest_contains_only_channel_and_codex_bindings(self):
        manifest = json.loads((Path(__file__).parents[1] / 'polaris-application.json').read_text())
        self.assertEqual(set(manifest['requires']), {'feishuRead', 'feishuReply', 'codexGet', 'codexSend'})
        self.assertIn('org.polaris.codex-cli', manifest['dependencies'])
        self.assertIn('bridge_output', manifest['callbacks'])


if __name__ == '__main__':
    unittest.main()
