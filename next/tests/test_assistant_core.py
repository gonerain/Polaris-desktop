import json
import threading
import unittest
from components.assistant.loop import AgentLoop
from components.assistant.model import ModelError
from components.assistant.context import Results
from components.assistant.tools import ToolExecutor
from polaris_platform.protocol import PlatformError


def tool(name, args, identity='c1'):
    return {'id': identity, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class Model:
    def __init__(self, replies): self.replies, self.requests = iter(replies), []
    def complete(self, messages, tools, cancel, timeout=30):
        self.requests.append((messages, tools))
        value = next(self.replies)
        return value(messages) if callable(value) else value
    def review(self, *args): raise AssertionError('No compulsory second model pass')


class Executor:
    allowed = True
    def __init__(self, value=None): self.value, self.calls = value, []
    def execute(self, name, args, cancel):
        self.calls.append((name, args))
        return self.value if self.value is not None else {'status': 'accepted'}


class CoreTests(unittest.TestCase):
    def test_batch_selection_filters_full_result_without_reexecuting(self):
        payload = {'a/b': [{'id': str(i), 'marked': i % 2 == 0, 'reply': 'x' * 10000} for i in range(10)]}
        def select(messages):
            ref = json.loads(messages[-1]['content'])['result_ref']
            return {'tool_calls': [tool('select_result', dict(result_ref=ref, path='/a~1b',
                where={'marked': True}, fields=['id'], offset=1, limit=2), 'c2')]}
        def finish(messages):
            result = json.loads(messages[-1]['content'])
            self.assertEqual(result, dict(items=[{'id': '2'}, {'id': '4'}], matched=5, offset=1, more=True))
            return {'content': '已找到'}
        model = Model([{'tool_calls': [tool('components', {})]}, select, finish]);executor = Executor(payload)
        AgentLoop(model).run('筛选', [], executor, threading.Event())
        self.assertEqual(len(executor.calls), 1)

    def test_selection_distinguishes_missing_null_and_boolean_from_number(self):
        results = Results();results.add('c1', [{'x': True}, {'x': 1}, {'x': None}, {}])
        self.assertEqual(results.select('r1', where={'x': 1})['items'], [{'x': 1}])
        self.assertEqual(results.select('r1', where={'x': True})['items'], [{'x': True}])
        self.assertEqual(results.select('r1', where={'x': None})['items'], [{'x': None}])
        with self.assertRaises(ValueError): results.select('r1', limit=100000)
        with self.assertRaises(ValueError): results.select('r1', where={'x': {'$eq': True}})
        with self.assertRaises(ValueError): results.select('unknown')

    def test_initial_catalog_allows_direct_calls_but_rechecks_live_metadata(self):
        record = {'id': 'toy', 'description': {'operations': {
            'get': {'access': 'read', 'parameters': {'type': 'object'}},
            'hidden': {'access': 'write', 'parameters': {'type': 'object'}}}}}
        class Context:
            def call(self, target, op, params):
                if op == 'discover': return {'components': [record]}
                if op == 'describe': return record
                return {'reply': 'exact-answer'}
        executor = ToolExecutor(Context(), [{'target': 'toy', 'operation': 'get'}], 'collaboration')
        def first(messages):
            self.assertIn('parameters', messages[0]['content'])
            self.assertNotIn('hidden', messages[0]['content'])
            return {'tool_calls': [tool('call', dict(component='toy', operation='get', arguments={}))]}
        model = Model([first, {'content': 'exact-answer'}])
        self.assertEqual(AgentLoop(model).run('查询', [], executor, threading.Event()).text, 'exact-answer')
        record['description']['operations']['get']['parameters']['required'] = ['new']
        with self.assertRaisesRegex(PlatformError, '操作说明已改变'):
            executor.execute('call', dict(component='toy', operation='get'), threading.Event())

    def test_plain_chat_is_one_request_and_keeps_conversation(self):
        model = Model([{'content': '你好'}])
        result = AgentLoop(model).run('好久不见', [{'role': 'user', 'content': 'old'}], Executor(), threading.Event())
        self.assertEqual(result.text, '你好')
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(model.requests[0][0][1]['content'], 'old')
        self.assertEqual(result.history[-1]['content'], '你好')

    def test_large_result_is_bounded_and_can_be_read_by_reference(self):
        payload = {'sessions': [{'id': 'chosen', 'reply': '秘密正文' * 15000}], 'status': 'ok'}
        def second(messages):
            encoded = json.loads(messages[-1]['content'])
            self.assertLess(len(messages[-1]['content']), 3000)
            self.assertEqual(encoded['result_ref'], 'r1')
            return {'tool_calls': [tool('read_result', {'result_ref': 'r1', 'path': '/sessions/0/id'}, 'c2')]}
        def third(messages):
            self.assertEqual(json.loads(messages[-1]['content'])['value'], 'chosen')
            return {'content': '找到了'}
        model = Model([{'tool_calls': [tool('call', {'component': 'toy', 'operation': 'get', 'arguments': {}})]}, second, third])
        executor = Executor(payload)
        self.assertEqual(AgentLoop(model).run('查询', [], executor, threading.Event()).text, '找到了')
        self.assertEqual(len(executor.calls), 1)
        self.assertLess(sum(len(json.dumps(m, ensure_ascii=False)) for m, _ in model.requests), 16000)

    def test_full_result_is_preserved_and_refs_do_not_cross_runs(self):
        results = Results(); value = {'huge': 'ab' * 10000, 'a/b': [7]}
        results.add('c', value)
        self.assertEqual(results.read('r1', '/a~1b/0')['value'], 7)
        first = results.read('r1', '/huge', limit=4000)
        self.assertTrue(first['more'])
        self.assertEqual(first['total_chars'], 20002)
        self.assertEqual(results.values['r1'], value)
        with self.assertRaises(ValueError): Results().read('r1')

    def test_error_result_reaches_model_with_exact_platform_code(self):
        class Denied(Executor):
            def execute(self, *args): raise PlatformError('permission_required', '没有权限')
        def finish(messages):
            self.assertEqual(json.loads(messages[-1]['content'])['code'], 'permission_required')
            return {'content': '需要授权'}
        model = Model([{'tool_calls': [tool('call', {'component': 'toy', 'operation': 'write', 'arguments': {}})]}, finish])
        self.assertEqual(AgentLoop(model).run('写入', [], Denied(), threading.Event()).text, '需要授权')

    def test_final_budget_reserves_reply_and_does_not_resubmit_tools(self):
        model = Model([{'tool_calls': [tool('call', {'component': 'toy', 'operation': 'write', 'arguments': {}})]}, {'content': '已接收，尚未完成'}])
        executor = Executor()
        result = AgentLoop(model, max_calls=2).run('写入', [], executor, threading.Event())
        self.assertEqual(model.requests[-1][1], [])
        self.assertEqual(len(executor.calls), 1)
        self.assertIn('尚未完成', result.text)

    def test_cancel_during_batch_prevents_remaining_actions(self):
        cancel = threading.Event()
        class Cancelling(Executor):
            def execute(self, *args): self.calls.append(1); cancel.set(); return {'ok': True}
        model = Model([{'tool_calls': [tool('components', {}, 'a'), tool('components', {}, 'b')]}]); executor = Cancelling()
        with self.assertRaisesRegex(ModelError, '取消'): AgentLoop(model).run('查询', [], executor, cancel)
        self.assertEqual(len(executor.calls), 1)

    def test_no_tool_permission_means_empty_toolset(self):
        executor = Executor(); executor.allowed = []
        model = Model([{'content': '普通对话'}])
        AgentLoop(model).run('你好', [], executor, threading.Event())
        self.assertEqual(model.requests[0][1], [])

    def test_invalid_batch_is_rejected_before_any_action(self):
        executor = Executor(); model = Model([{'tool_calls': [tool('components', {}, 'a'), tool('components', {}, 'a')]}])
        with self.assertRaises(ModelError): AgentLoop(model).run('查询', [], executor, threading.Event())
        self.assertEqual(executor.calls, [])

    def test_oversized_thinking_stops_before_another_network_request(self):
        model = Model([{'reasoning_content': '想' * 40000, 'tool_calls': [tool('components', {})]}])
        with self.assertRaisesRegex(ModelError, '上下文超过预算'):
            AgentLoop(model).run('查询', [], Executor(), threading.Event())
        self.assertEqual(len(model.requests), 1)

    def test_reused_tool_id_across_rounds_cannot_alias_a_previous_result(self):
        model = Model([{'tool_calls': [tool('components', {})]}, {'tool_calls': [tool('components', {})]}])
        executor = Executor()
        with self.assertRaisesRegex(ModelError, '标识重复'):
            AgentLoop(model).run('查询', [], executor, threading.Event())
        self.assertEqual(len(executor.calls), 1)

    def test_tool_catalog_is_compact_and_human_only_is_not_model_callable(self):
        record = {'id': 'toy', 'manifest': {'name': '测试'}, 'description': {'operations': {
            'get': {'parameters': {'description': 'x' * 20000}}, 'respond': {'humanOnly': True}}}}
        class Context:
            def call(self, target, op, params): return {'components': [record]} if op == 'discover' else record
        executor = ToolExecutor(Context(), [{'target': 'toy', 'operation': 'get'}, {'target': 'toy', 'operation': 'respond'}], 'collaboration')
        catalog = executor.execute('components', {}, threading.Event())
        self.assertLess(len(json.dumps(catalog)), 500)
        self.assertEqual(catalog['components'][0]['operations'][0]['name'], 'get')
        self.assertNotIn('respond', executor.filtered(record)['description']['operations'])

    def test_writes_are_deduplicated_and_unknown_writes_are_not_retried(self):
        class Context:
            writes = 0
            def call(self, target, op, params):
                if op == 'describe': return {'id': 'toy', 'description': {'operations': {'write': {'access': 'write'}}}}
                self.writes += 1
                raise TimeoutError('unknown')
        ctx = Context(); executor = ToolExecutor(ctx, [{'target': 'toy', 'operation': 'write'}], 'collaboration')
        executor.execute('help', {'component': 'toy', 'operation': 'write'}, threading.Event())
        args = {'component': 'toy', 'operation': 'write', 'arguments': {}}
        with self.assertRaises(TimeoutError): executor.execute('call', args, threading.Event())
        with self.assertRaises(PlatformError): executor.execute('call', args, threading.Event())
        self.assertEqual(ctx.writes, 1)
