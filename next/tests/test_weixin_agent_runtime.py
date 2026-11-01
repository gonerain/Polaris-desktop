"""Agent integration uses fake model/transport and actual platform context calls."""
from pathlib import Path
import sys
import threading
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components/weixin'))
import test_weixin_component as fixtures
Credentials, ACCOUNT = fixtures.Credentials, fixtures.ACCOUNT
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from polaris_weixin.agent import WeixinAgent
from polaris_weixin.controller import ToolExecutor


class Model:
    def __init__(self): self.step = 0
    def complete(self, messages, tools, cancel, timeout=30):
        self.step += 1
        if self.step == 1:
            return {'role': 'assistant', 'tool_calls': [{'id':'h','type':'function','function':{'name':'help','arguments':'{"component":"toy"}'}}]}
        if self.step == 2:
            return {'role':'assistant','tool_calls':[{'id':'c','type':'function','function':{'name':'call','arguments':'{"component":"toy","operation":"echo","arguments":{"text":"ok"}}'}}]}
        return {'role':'assistant','content':'完成'}


class AgentRuntimeTests(unittest.TestCase):
    call = fixtures.WeixinComponentTests.call
    wait = fixtures.WeixinComponentTests.wait
    tearDown = fixtures.WeixinComponentTests.tearDown
    def setUp(self):
        fixtures.WeixinComponentTests.setUp(self)
        self.effects = []
        owner = self
        class Toy(Component):
            def __init__(self):
                super().__init__()
                self.operation('echo', access='write')(self.echo)
            def echo(self, text):
                owner.effects.append(text)
                return {'text': text}
        self.runtime.install({'id':'toy','name':'Toy','version':'1','platformApi':1,'entry':{'mode':'inprocess'}}, Toy)
        self.runtime.start_component('toy')
        for target, op in [('toy','echo'),('collaboration','discover'),('collaboration','describe')]:
            self.runtime.grant('user', target, op)
        self.context = self.runtime.user_context('user')
        self.component.agent.agent = WeixinAgent(Model())
        self.component.client.account = dict(ACCOUNT)
        self.component.client.credentials = Credentials(ACCOUNT)
        self.component.client.state = 'connected'
    def enable(self):
        return self.call('configure_agent', enabled=True, allowed=[{'target':'toy','operation':'echo'}])
    def receive(self, identity='fresh', timestamp=None):
        with self.component.client._lock:
            self.component.client.receive(dict(message_id=identity, message_type=1, message_state=2,
                from_user_id='fake-user', context_token='fake-context', create_time_ms=timestamp,
                item_list=[{'type':1,'text_item':{'text':'测试'}}]))
    def test_fake_model_real_context_and_confirmed_history(self):
        self.enable(); self.receive(timestamp=time.time()*1000)
        self.wait(lambda: len(self.component.agent.history) == 2)
        self.assertEqual(self.effects, ['ok'])
        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(self.fake.sent[0]['item_list'][0]['text_item']['text'], '完成')
    def test_old_missing_and_duplicate_messages_never_trigger(self):
        self.receive('before', time.time()*1000)
        self.enable()
        self.receive('missing'); self.receive('old-time', 1000)
        self.receive('before', time.time()*1000)
        time.sleep(.05)
        self.assertEqual(self.effects, [])
        self.assertEqual(self.fake.sent, [])
    def test_allowlist_and_revalidation(self):
        class Ctx:
            def call(_, target, operation, params):
                return self.runtime.client('user').call(target, operation, params, context=self.context)
        executor = ToolExecutor(Ctx(), [{'target':'toy','operation':'echo'}], 'collaboration')
        cancel = threading.Event()
        with self.assertRaises(PlatformError):
            executor.execute('call', {'component':'toy','operation':'echo'}, cancel)
        executor.execute('help', {'component':'toy'}, cancel)
        self.runtime.revoke('user','toy','echo')
        with self.assertRaises(PlatformError):
            executor.execute('call', {'component':'toy','operation':'echo','arguments':{'text':'bad'}}, cancel)
        with self.assertRaises(PlatformError):
            executor.execute('help', {'component':'collaboration'}, cancel)
        self.assertEqual(self.effects, [])
    def test_write_deduplicates_success_and_unknown_within_turn(self):
        calls = []
        class Ctx:
            def call(_, target, operation, params):
                if operation == 'describe':
                    return {'id':'toy','description':{'operations':{'echo':{'access':'write'}}}}
                calls.append(params)
                if params.get('fail'):
                    raise TimeoutError()
                return {'ok': True}
        executor = ToolExecutor(Ctx(), [{'target':'toy','operation':'echo'}], 'collaboration')
        cancel = threading.Event()
        executor.execute('help', {'component':'toy'}, cancel)
        args = {'component':'toy','operation':'echo','arguments':{'text':'same'}}
        self.assertEqual(executor.execute('call', args, cancel), executor.execute('call', args, cancel))
        args['arguments'] = {'fail': True}
        with self.assertRaises(TimeoutError): executor.execute('call', args, cancel)
        with self.assertRaises(PlatformError): executor.execute('call', args, cancel)
        self.assertEqual(len(calls), 2)

    def test_settings_restart_stays_disabled_and_context_never_saved(self):
        from polaris_weixin.controller import AgentController
        self.enable()
        restored = AgentController(self.component.client, self.component.agent.path, lambda: None)
        self.assertFalse(restored.enabled)
        self.assertIsNone(restored.ctx)
        self.assertEqual(restored.allowed, [{'target':'toy','operation':'echo'}])
        self.assertEqual(set(__import__('json').loads(restored.path.read_text())), {'version','allowed'})

    def test_actual_manifest_identity_cannot_be_selected_or_called(self):
        self.assertEqual(self.component.agent.own_id, self.identity)
        catalog = self.call('agent_catalog')['components']
        self.assertNotIn(self.identity, [r['id'] for r in catalog])
        with self.assertRaises(PlatformError):
            self.call('configure_agent', enabled=True, allowed=[{'target':self.identity,'operation':'send'}])
        self.component.agent.allowed = [{'target':self.identity,'operation':'configure_agent'}]
        with self.assertRaises(PlatformError):
            self.call('configure_agent', enabled=True)
        executor = ToolExecutor(None, [{'target':self.identity,'operation':'send'}], 'collaboration', self.identity)
        with self.assertRaises(PlatformError):
            executor.execute('help', {'component':self.identity}, threading.Event())

    def test_logout_and_account_change_clear_previous_history(self):
        self.enable()
        self.component.agent.history = [{'role':'user','content':'previous account secret'}]
        self.call('logout')
        self.assertEqual(self.component.agent.history, [])
        self.assertFalse(self.component.agent.enabled)
        self.component.agent.history = [{'role':'user','content':'old'}]
        self.component.client.on_account_changed()
        self.assertEqual(self.component.agent.history, [])

    def test_new_conversation_preserves_explicit_context_and_enabled_state(self):
        self.enable()
        controller = self.component.agent
        old_cancel, old_ctx = controller.cancel, controller.ctx
        controller.history = [{'role':'user','content':'old'}]
        self.call('new_conversation')
        self.assertTrue(old_cancel.is_set())
        self.assertTrue(controller.enabled)
        self.assertIs(controller.ctx, old_ctx)
        self.assertEqual(controller.history, [])
        self.assertEqual(len(controller.queue), 0)

    def test_invalid_key_enable_is_safe_platform_error(self):
        from unittest.mock import patch
        self.component.agent.agent = None
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'invalid private key'}):
            with self.assertRaises(PlatformError) as caught:
                self.enable()
        self.assertIn('DEEPSEEK_API_KEY', str(caught.exception))
        self.assertNotIn('invalid private key', str(caught.exception))
        self.assertFalse(self.component.agent.enabled)

    def test_revoked_send_prevents_reply_and_history_commit(self):
        self.enable()
        self.runtime.revoke('user', self.identity, 'send')
        self.receive(timestamp=time.time()*1000)
        self.wait(lambda: not self.component.agent.enabled)
        self.assertEqual(self.effects, ['ok'])
        self.assertEqual(self.fake.sent, [])
        self.assertEqual(self.component.agent.history, [])
        self.assertTrue(self.component.agent.error)

    def test_revoked_get_prevents_forwarding_text_to_model(self):
        model = self.component.agent.agent.model
        self.enable()
        self.runtime.revoke('user', self.identity, 'get')
        self.receive(timestamp=time.time()*1000)
        self.wait(lambda: not self.component.agent.enabled)
        self.assertEqual(model.step, 0)
        self.assertEqual(self.effects, [])
        self.assertEqual(self.fake.sent, [])
        self.assertTrue(self.component.agent.error)

    def test_disconnect_cancels_late_model(self):
        started, release = threading.Event(), threading.Event()
        class Slow:
            def run(_, text, history, tools, cancel):
                from polaris_weixin.agent import AgentResult
                started.set(); release.wait(2)
                return AgentResult('迟到', [])
        self.component.agent.agent = Slow()
        self.enable(); self.receive(timestamp=time.time()*1000)
        self.assertTrue(started.wait(1))
        self.call('disconnect'); release.set()
        self.wait(lambda: not self.component.agent.busy)
        self.assertFalse(self.call('agent_settings')['enabled'])
        self.assertEqual(self.fake.sent, [])
    def test_unknown_send_not_retried_or_committed(self):
        original = self.fake.request
        def fail(origin, endpoint, body, **kwargs):
            if endpoint.endswith('sendmessage'):
                self.fake.sent.append(body['msg']); raise TimeoutError()
            return original(origin, endpoint, body, **kwargs)
        self.fake.request = fail
        self.enable(); self.receive(timestamp=time.time()*1000)
        self.wait(lambda: bool(self.call('agent_settings')['error']))
        self.assertEqual(len(self.fake.sent), 1)
        self.assertEqual(self.component.agent.history, [])
        self.assertFalse(self.call('agent_settings')['enabled'])

if __name__ == '__main__': unittest.main()
