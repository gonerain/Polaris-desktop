import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error

from components.assistant.loop import AgentLoop
from components.assistant.model import DeepSeek, ModelError


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


class TransportTests(unittest.TestCase):
    def test_transport_errors_report_safe_status_and_timeout(self):
            secret = 'fake-key-private123'
            errors = [
                (urllib.error.HTTPError('https://example.test/' + secret, 400,
                                       secret, {'Secret': secret}, None), 'DeepSeek 请求失败（HTTP 400）'),
                (TimeoutError(secret), 'DeepSeek 请求超时'),
                (urllib.error.URLError(TimeoutError(secret)), 'DeepSeek 请求超时'),
                (urllib.error.URLError(secret), 'DeepSeek 请求失败，请检查网络或配置'),
            ]
            for error, expected in errors:
                class Opener:
                    def open(self, *args, **kwargs): raise error
                with self.subTest(error=type(error).__name__), self.assertRaises(ModelError) as caught:
                    DeepSeek(secret, Opener()).complete([], [], threading.Event())
                self.assertEqual(str(caught.exception), expected)
                self.assertNotIn(secret, str(caught.exception))

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
            self.assertEqual(result['reasoning_content'], 'hidden')
            self.assertEqual(opener.payload['thinking'], {'type': 'enabled'})
            self.assertEqual(opener.payload['reasoning_effort'], 'max')
            self.assertEqual(opener.payload['max_tokens'], 4096)
            self.assertEqual(opener.payload['model'], 'deepseek-flash')
            self.assertFalse(opener.payload['stream'])

    def test_thinking_tool_context_is_returned_without_leaking_to_history(self):
            key = 'sk-thinking-secret123'
            thought = '私有思考 ' + key + '想' * 1000
            replies = iter([
                {'content': None, 'reasoning_content': thought,
                 'tool_calls': [tool('components', {})]},
                {'content': '完成', 'reasoning_content': '最终私有思考'},
            ])

            class Response:
                def __init__(self, message):
                    self.data = json.dumps({'choices': [{'message': message}]}, ensure_ascii=False).encode()
                def read(self, size):
                    chunk, self.data = self.data[:size], self.data[size:]
                    return chunk
                def close(self): pass

            class Opener:
                def __init__(self): self.payloads = []; self.timeouts = []
                def open(self, request, timeout):
                    self.payloads.append(json.loads(request.data))
                    self.timeouts.append(timeout)
                    return Response(next(replies))

            opener = Opener()
            model = DeepSeek(key, opener)
            # Exercise generation's tool loop without making an extra review request.
            model.review = None
            result = AgentLoop(model).run('查询', [], Executor(), threading.Event())
            context = opener.payloads[1]['messages']
            assistant = next(row for row in context if row['role'] == 'assistant')
            self.assertEqual(assistant['reasoning_content'], thought.replace(key, '[已隐藏密钥]'))
            self.assertNotIn(key, json.dumps(context))
            self.assertEqual(result.text, '完成')
            self.assertNotIn('reasoning_content', json.dumps(result.history))
            self.assertNotIn('私有思考', json.dumps(result.history, ensure_ascii=False))
            self.assertTrue(all(179 < timeout <= 180 for timeout in opener.timeouts))

    def test_printable_key_and_whitespace(self):
            model = DeepSeek('  fake!key-123  ')
            self.assertEqual(model.redact('fake!key-123'), '[已隐藏密钥]')
            DeepSeek('x' * 4096)
            for key in ('x' * 4097, 'fake key-123', 'fake\x7fkey-123'):
                with self.assertRaises(ModelError):
                    DeepSeek(key)

    def test_transport_rejects_invalid_types_and_late_cancel(self):
            for message in ({'content': {}}, {'content': 'ok', 'reasoning_content': {}}, {'content': 'ok', 'tool_calls': {}},
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

