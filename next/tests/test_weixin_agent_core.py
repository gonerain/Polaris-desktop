import json
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components/weixin'))
from polaris_weixin.agent import WeixinAgent
from polaris_weixin.model import DeepSeek, ModelError


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)
    def complete(self, *args, **kwargs):
        return next(self.replies)


def tool(name, args):
    return {'id': name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class Executor:
    def __init__(self):
        self.calls = []
    def execute(self, name, args, cancel):
        self.calls.append((name, args))
        return {'ok': True}


class CoreTests(unittest.TestCase):
    def test_help_gate_and_order(self):
        model = FakeModel([
            {'role': 'assistant', 'tool_calls': [tool('call', {'component': 'x'})]},
            {'role': 'assistant', 'tool_calls': [tool('help', {'component': 'x'}),
                tool('call', {'component': 'x', 'operation': 'get', 'arguments': {}})]},
            {'role': 'assistant', 'content': '完成'}])
        executor = Executor()
        result = WeixinAgent(model).run('查询', [], executor, threading.Event())
        self.assertEqual([x[0] for x in executor.calls], ['help', 'call'])
        self.assertEqual(result.text, '完成')
        self.assertEqual([x['role'] for x in result.history], ['user', 'assistant'])

    def test_unknown_tool_and_nonobject(self):
        model = FakeModel([{'tool_calls': [tool('__class__', {}), tool('components', [])]}, {'content': '好'}])
        executor = Executor()
        self.assertEqual(WeixinAgent(model).run('a', [], executor, threading.Event()).text, '好')
        self.assertEqual(executor.calls, [])

    def test_cancel_does_not_call(self):
        cancel = threading.Event(); cancel.set()
        executor = Executor()
        with self.assertRaises(ModelError):
            WeixinAgent(FakeModel([])).run('a', [], executor, cancel)
        self.assertEqual(executor.calls, [])

    def test_output_bound(self):
        result = WeixinAgent(FakeModel([{'content': '字' * 5000}])).run('a', [], Executor(), threading.Event())
        self.assertLessEqual(len(result.text), 2000)

    def test_fake_transport_and_redaction(self):
        key = 'sk-fakekey123456'
        class Response:
            def __init__(self):
                self.done = False
            def read(self, size):
                if self.done: return b''
                self.done = True
                return json.dumps({'choices': [{'message': {'content': key, 'reasoning_content': 'hidden'}}]}).encode()
            def close(self): pass
        class Opener:
            def open(self, request, timeout):
                self.payload = json.loads(request.data)
                return Response()
        opener = Opener()
        result = DeepSeek(key, opener).complete([], [], threading.Event())
        self.assertNotIn(key, str(result))
        self.assertNotIn('reasoning_content', result)
        self.assertEqual(opener.payload['model'], 'deepseek-flash')
        self.assertFalse(opener.payload['stream'])

    def test_empty_or_invalid_answer_is_error(self):
        for content in (None, '', '   ', {}, 1):
            with self.subTest(content=content), self.assertRaises(ModelError):
                WeixinAgent(FakeModel([{'content': content}])).run('a', [], Executor(), threading.Event())

    def test_model_error_propagates(self):
        class Broken:
            def complete(self, *args, **kwargs):
                raise ModelError('失败')
        with self.assertRaises(ModelError):
            WeixinAgent(Broken()).run('a', [], Executor(), threading.Event())

    def test_late_model_reply_cancelled(self):
        cancel = threading.Event()
        class Late:
            def complete(self, *args, **kwargs):
                cancel.set()
                return {'content': '迟到的正文'}
        with self.assertRaises(ModelError):
            WeixinAgent(Late()).run('a', [], Executor(), cancel)

    def test_interrupted_tool_propagates(self):
        class Interrupted:
            def execute(self, *args):
                raise InterruptedError('取消')
        with self.assertRaises(InterruptedError):
            WeixinAgent(FakeModel([{'tool_calls': [tool('components', {})]}])).run(
                'a', [], Interrupted(), threading.Event())

    def test_request_budget_raises(self):
        model = FakeModel([{'tool_calls': [tool('components', {})]}] * 6)
        with self.assertRaises(ModelError):
            WeixinAgent(model).run('a', [], Executor(), threading.Event())

    def test_printable_key_and_whitespace(self):
        model = DeepSeek('  fake!key-123  ')
        self.assertEqual(model.redact('fake!key-123'), '[已隐藏密钥]')
        DeepSeek('x' * 4096)
        for key in ('x' * 4097, 'fake key-123', 'fake\x7fkey-123'):
            with self.assertRaises(ModelError):
                DeepSeek(key)

    def test_transport_rejects_invalid_types_and_late_cancel(self):
        for message in ({'content': {}}, {'content': 'ok', 'tool_calls': {}},
                        {'content': 'ok', 'tool_calls': ['bad']}):
            class Response:
                def __init__(self): self.done = False
                def read(self, size):
                    if self.done: return b''
                    self.done = True
                    return json.dumps({'choices': [{'message': message}]}).encode()
                def close(self): pass
            class Opener:
                def open(self, *args, **kwargs): return Response()
            with self.assertRaises(ModelError):
                DeepSeek('fake-key123', Opener()).complete([], [], threading.Event())
        cancel = threading.Event()
        class LateResponse:
            def read(self, size):
                cancel.set()
                return b''
            def close(self): pass
        class LateOpener:
            def open(self, *args, **kwargs): return LateResponse()
        with self.assertRaises(ModelError):
            DeepSeek('fake-key123', LateOpener()).complete([], [], cancel)

    def test_bad_key(self):
        with self.assertRaises(ModelError): DeepSeek('bad\nkey')


if __name__ == '__main__': unittest.main()
