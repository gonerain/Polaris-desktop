"""Offline application orchestration tests: no model or real Feishu calls."""
import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import unittest

spec = importlib.util.spec_from_file_location('feishu_agent_backend', Path(__file__).parents[1] / 'backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def incoming(index, chat='oc_chat', thread='', kind='text', text=None, direction='inbound'):
    return dict(messageId='om_' + str(index), chatId=chat, direction=direction, messageType=kind,
        text=text if text is not None else '问题 ' + str(index), normalized={'conversation': {'thread_id': thread}})


class Context:
    def __init__(self, directory):
        self.data_directory = directory
        self.application_id = 'app_fixture'
        self.stopped = threading.Event()
        self.bindings = {alias: dict(instanceId='bot' if alias.startswith('feishu') else 'agent')
                         for alias in ('feishuStatus', 'feishuRead', 'feishuReply', 'agentStatus', 'agentReply')}
        for alias, operation, label, group in backend.TOOLS:
            self.bindings[alias] = dict(instanceId=group + '-instance', target=group + '-instance', operation=operation)
        self.messages = []
        self.calls = []
        self.published = {}
        self.fail = ''
        self.connection_state = 'connected'
        self.connection_error = ''
        self.entered = threading.Event()
        self.release = None
    def publish(self, value): self.published = value
    def call(self, alias, params):
        self.calls.append((alias, dict(params)))
        if self.fail == alias: raise ValueError('测试失败')
        if alias == 'feishuStatus': return dict(connectionState=self.connection_state, instanceName='测试飞书', lastError=self.connection_error)
        if alias == 'agentStatus': return dict(ready=True, model='glm-5.3-flash', detail='')
        if alias == 'feishuRead':
            after = params['after']
            items = self.messages[after:after + params['limit']]
            return dict(items=items, nextCursor=after + len(items))
        if alias == 'agentReply':
            self.entered.set()
            if self.release: self.release.wait()
            return dict(text='回答：' + params['text'], turn='turn_test')
        if alias == 'feishuReply': return dict(messageId='om_sent')
        raise AssertionError(alias)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.context = Context(Path(self.temporary.name))
        self.service = backend.create(self.context)
        self.service.interval = .01
    def tearDown(self):
        self.context.stopped.set()
        if self.context.release: self.context.release.set()
        self.service.stop()
        self.temporary.cleanup()
    def wait(self, condition):
        end = time.monotonic() + 3
        while not condition() and time.monotonic() < end: time.sleep(.005)
        self.assertTrue(condition(), self.context.published)
    def start(self):
        self.service.start()
        self.wait(lambda: self.context.published['initialized'])
    def test_first_start_skips_all_history_pages_and_new_messages_use_same_instances(self):
        self.context.messages = [incoming(index) for index in range(1101)]
        self.start()
        self.assertEqual(self.service.data['cursor'], 1101)
        self.assertEqual(self.service.data['tasks'], [])
        self.context.messages.append(incoming('new'))
        self.wait(lambda: bool(self.service.data['tasks']) and self.service.data['tasks'][0]['state'] == 'done')
        generate = next(params for alias, params in self.context.calls if alias == 'agentReply')
        self.assertEqual(generate['allowed'], self.service._allowed_tools())
        self.assertEqual(generate['text'], '问题 new')
        reply = next(params for alias, params in self.context.calls if alias == 'feishuReply')
        self.assertEqual(reply['message_id'], 'om_new')
        self.assertFalse(reply['reply_in_thread'])
        self.assertEqual(self.context.published['agentInstance'], 'agent')
    def test_text_post_only_thread_conversations_and_no_echo(self):
        self.start()
        self.context.messages.extend([incoming(1, thread='thread_a'), incoming(2, thread='thread_a', kind='post'),
            incoming(3, thread='thread_b'), incoming(4, kind='image'), incoming(5, direction='outbound'), incoming(6, text='')])
        self.wait(lambda: len(self.service.data['tasks']) == 3 and all(t['state'] == 'done' for t in self.service.data['tasks']))
        tasks = self.service.data['tasks']
        self.assertEqual(tasks[0]['conversation'], tasks[1]['conversation'])
        self.assertNotEqual(tasks[0]['conversation'], tasks[2]['conversation'])
        self.assertTrue(all(params['reply_in_thread'] for alias, params in self.context.calls if alias == 'feishuReply'))
    def test_generation_failure_blocks_same_conversation_until_manual_continue(self):
        self.start()
        self.context.fail = 'agentReply'
        self.context.messages.extend([incoming(1), incoming(2)])
        self.wait(lambda: len(self.service.data['tasks']) == 2 and self.service.data['tasks'][0]['state'] == 'failed')
        self.assertEqual(self.service.data['tasks'][1]['state'], 'pending')
        self.context.fail = ''
        self.service.handle('retry', {'taskId': self.service.data['tasks'][0]['id']})
        self.wait(lambda: all(t['state'] == 'done' for t in self.service.data['tasks']))
    def test_unknown_send_is_never_automatically_repeated_and_answer_is_reused(self):
        self.start()
        self.context.fail = 'feishuReply'
        self.context.messages.append(incoming(1))
        self.wait(lambda: bool(self.service.data['tasks']) and self.service.data['tasks'][0]['state'] == 'unknown')
        time.sleep(.05)
        self.assertEqual(len([a for a, p in self.context.calls if a == 'feishuReply']), 1)
        task = self.service.data['tasks'][0]
        answer = task['answer']
        self.context.fail = ''
        self.service.handle('resend', {'taskId': task['id']})
        self.wait(lambda: task['state'] == 'done')
        self.assertEqual(task['answer'], answer)
        self.assertEqual(len([a for a, p in self.context.calls if a == 'agentReply']), 1)
    def test_stop_during_model_call_records_answer_without_sending_then_restart_resumes(self):
        self.context.release = threading.Event()
        self.start()
        self.context.messages.append(incoming(1))
        self.assertTrue(self.context.entered.wait(3))
        self.context.stopped.set()
        stopping = threading.Thread(target=self.service.stop)
        stopping.start()
        self.context.release.set()
        stopping.join(3)
        self.assertFalse(stopping.is_alive())
        self.assertEqual(self.service.data['tasks'][0]['state'], 'ready')
        self.assertFalse(any(a == 'feishuReply' for a, p in self.context.calls))
        next_context = Context(self.context.data_directory)
        next_context.messages = self.context.messages
        next_service = backend.create(next_context)
        next_service.interval = .01
        try:
            next_service.start()
            self.wait(lambda: next_service.data['tasks'][0]['state'] == 'done')
            self.assertFalse(any(a == 'agentReply' for a, p in next_context.calls))
        finally:
            next_context.stopped.set()
            next_service.stop()
    def test_explicit_feishu_rejection_retries_original_answer_without_model_call(self):
        class Rejection(Exception): code = 'feishu_99991672'
        original = self.context.call
        def rejecting(alias, params):
            if alias == 'feishuReply': raise Rejection('飞书权限不足')
            return original(alias, params)
        self.context.call = rejecting
        self.start()
        self.context.messages.append(incoming(1))
        self.wait(lambda: bool(self.service.data['tasks']) and self.service.data['tasks'][0]['state'] == 'send_failed')
        task = self.service.data['tasks'][0]
        self.context.call = original
        self.service.handle('resend', {'taskId': task['id']})
        self.wait(lambda: task['state'] == 'done')
        self.assertEqual(len([a for a, p in self.context.calls if a == 'agentReply']), 1)
    def test_older_failed_requests_remain_visible_after_recent_forty(self):
        self.service.data['tasks'] = [dict(id='old_failed', state='failed')]
        self.service.data['tasks'].extend(dict(id=str(i), state='done') for i in range(45))
        self.service._publish()
        self.assertEqual(len(self.context.published['tasks']), 41)
        self.assertIn('old_failed', [task['id'] for task in self.context.published['tasks']])
    def test_oversized_request_can_be_explicitly_skipped_to_process_next_message(self):
        self.start()
        self.context.messages.extend([incoming(1, text='长' * 8001), incoming(2, text='短消息')])
        self.wait(lambda: len(self.service.data['tasks']) == 2 and self.service.data['tasks'][0]['state'] == 'failed')
        first = self.service.data['tasks'][0]
        self.assertEqual(self.service.data['tasks'][1]['state'], 'pending')
        self.service.handle('skip', {'taskId': first['id']})
        self.wait(lambda: self.service.data['tasks'][1]['state'] == 'done')
        self.assertEqual(first['state'], 'skipped')
        self.assertEqual(len(first['text']), 8001)
        self.assertEqual(len([a for a, p in self.context.calls if a == 'agentReply']), 1)
    def test_connecting_waits_without_cursor_or_model_then_connected_initializes(self):
        self.context.connection_state = 'connecting'
        self.context.messages = [incoming('old')]
        self.service.start()
        self.wait(lambda: self.context.published.get('feishu', {}).get('connectionState') == 'connecting')
        time.sleep(.03)
        self.assertIsNone(self.service.data['cursor'])
        self.assertFalse(any(alias in ('feishuRead', 'agentStatus', 'agentReply', 'feishuReply') for alias, params in self.context.calls))
        self.assertFalse(self.service.error)
        self.context.connection_state = 'connected'
        self.wait(lambda: self.context.published['initialized'])
        self.assertEqual(self.service.data['tasks'], [])
        self.context.messages.append(incoming('new'))
        self.wait(lambda: bool(self.service.data['tasks']) and self.service.data['tasks'][0]['state'] == 'done')
    def test_connecting_to_error_pauses_for_manual_continue(self):
        self.context.connection_state = 'connecting'
        self.service.start()
        self.wait(lambda: self.context.published.get('feishu', {}).get('connectionState') == 'connecting')
        self.context.connection_state = 'error'
        self.context.connection_error = '真实连接失败根因'
        self.wait(lambda: bool(self.service.error))
        self.assertEqual(self.service.error, '真实连接失败根因')
        self.assertIsNone(self.service.data['cursor'])
        self.context.connection_state = 'connected'
        self.context.connection_error = ''
        time.sleep(.03)
        self.assertIsNone(self.service.data['cursor'])
        self.service.handle('continue', {})
        self.wait(lambda: self.context.published['initialized'])
    def test_allowed_tools_are_exact_twenty_one_bindings_without_channel_agent_or_directory(self):
        self.context.bindings['directoryExtra'] = dict(instanceId='directory', target='directory', operation='discover')
        self.context.bindings['feishuExtra'] = dict(instanceId='bot', target='bot', operation='send')
        expected = [dict(target=self.context.bindings[alias]['target'], operation=self.context.bindings[alias]['operation'])
                    for alias, operation, label, group in backend.TOOLS]
        self.assertEqual(len(expected), 21)
        self.assertEqual(self.service._allowed_tools(), expected)
        self.assertEqual({item['target'] for item in expected}, {'schedule-instance', 'bridge-instance'})
    def test_tool_group_instance_consistency_and_provider_rebinding(self):
        for key, title in backend.TOOL_GROUPS:
            aliases = [alias for alias, operation, label, group in backend.TOOLS if group == key]
            self.context.bindings[aliases[-1]]['instanceId'] = 'wrong'
            with self.assertRaisesRegex(ValueError, '同一个组件实例'): self.service._check_bindings()
            for alias in aliases:
                self.context.bindings[alias].update(instanceId='replacement-' + key, target='replacement-' + key)
            self.context.bindings[aliases[0]]['operation'] = 'provider_specific_entry'
            self.service._check_bindings()
        self.assertEqual(self.service._allowed_tools()[0]['operation'], 'provider_specific_entry')
        self.assertEqual({row['target'] for row in self.service._allowed_tools()}, {'replacement-schedule', 'replacement-bridge'})
    def test_manifest_declares_exact_tool_contracts_and_no_directory_alias(self):
        import json
        manifest = json.loads((Path(__file__).parents[1] / 'polaris-application.json').read_text())
        self.assertEqual(manifest['version'], '0.2.0')
        self.assertEqual(len(manifest['requires']), 26)
        for alias, operation, label, group in backend.TOOLS:
            prefix = 'polaris.schedule.' if group == 'schedule' else 'polaris.agent-bridge.'
            self.assertEqual(manifest['requires'][alias]['contract'], prefix + operation.replace('_', '-') + '@1')
        self.assertFalse(any('discover' in row['contract'] or 'describe' in row['contract'] for row in manifest['requires'].values()))
    def test_binding_group_must_reference_exact_same_instance(self):
        self.context.bindings['agentReply']['instanceId'] = 'other_agent'
        with self.assertRaisesRegex(ValueError, '同一个组件实例'): self.service.start()
    def test_status_error_can_be_fixed_and_manually_continued(self):
        self.context.fail = 'agentStatus'
        self.service.start()
        self.wait(lambda: bool(self.service.error))
        self.context.fail = ''
        self.service.handle('continue', {})
        self.wait(lambda: self.context.published['initialized'])
        self.assertTrue(self.service.thread.is_alive())
    def test_persisted_inflight_states_require_attention_without_losing_answers(self):
        self.service.data['tasks'] = [dict(id='sending', state='sending', answer='保留回答'), dict(id='generating', state='generating', answer='')]
        self.service._save()
        recovered = backend.create(self.context)
        self.assertEqual(recovered.data['tasks'][0]['state'], 'unknown')
        self.assertEqual(recovered.data['tasks'][0]['answer'], '保留回答')
        self.assertEqual(recovered.data['tasks'][1]['state'], 'failed')


if __name__ == '__main__': unittest.main()
