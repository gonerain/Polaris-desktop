import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/weixin'))
from components.assistant.model import ChatModel, ModelError
from components.assistant.usage import UsageLog


class Response:
    def __init__(self, payload): self.data = json.dumps(payload).encode()
    def read(self, size):
        result, self.data = self.data[:size], self.data[size:]
        return result
    def close(self): pass


class AccountingTests(unittest.TestCase):
    def test_generation_and_review_record_real_tokens_without_message_content(self):
        class Opener:
            def open(self, request, timeout):
                payload = json.loads(request.data)
                message = {'content': 'private reply', 'reasoning_content': 'private thought'}
                if payload.get('tools'):
                    message['tool_calls'] = [{'id': 'call', 'function': {'name': 'review_reply', 'arguments':
                        json.dumps({'needs_tools': False, 'reply': 'private reply', 'reason': ''})}}]
                return Response({'id': 'provider-request-1', 'model': 'glm-5.3-flash', 'usage': {
                    'prompt_tokens': 2000, 'completion_tokens': 3000, 'total_tokens': 5000,
                    'prompt_tokens_details': {'cached_tokens': 1000},
                    'completion_tokens_details': {'reasoning_tokens': 2500}}, 'choices': [{'message': message}]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'usage.jsonl'
            model = ChatModel('private-api-key', Opener(), provider='bigmodel', usage_path=path)
            model.begin_run()
            model.complete([{'role': 'user', 'content': 'private question'},
                            {'role': 'tool', 'content': 'private tool result'}], [], threading.Event())
            model.complete([{'role': 'user', 'content': 'private question'}], [], threading.Event())
            raw = path.read_text(); rows = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual([r['phase'] for r in rows], ['generate', 'generate'])
            self.assertEqual([r['sequence'] for r in rows], [1, 2])
            self.assertEqual(rows[0]['runId'], rows[1]['runId'])
            self.assertEqual(rows[0]['usage']['cached_tokens'], 1000)
            self.assertEqual(rows[0]['usage']['reasoning_tokens'], 2500)
            self.assertEqual(rows[0]['toolResultChars'], len('private tool result'))
            self.assertNotIn('private', raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_http_failure_recorded_once_and_does_not_retry(self):
        class Opener:
            count = 0
            def open(self, *args, **kwargs):
                self.count += 1
                raise urllib.error.HTTPError('https://open.bigmodel.cn', 503, 'secret error text', {}, None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'usage.jsonl'; opener = Opener()
            model = ChatModel('private-api-key', opener, provider='bigmodel', usage_path=path)
            with self.assertRaises(ModelError): model.complete([], [], threading.Event())
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(opener.count, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['httpStatus'], 503)
            self.assertNotIn('secret', path.read_text())

    def test_rotation_retains_bounded_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'usage.jsonl'; path.write_text('x' * (1024 * 1024))
            UsageLog(path).append({'status': 'ok'})
            self.assertTrue(path.with_suffix('.jsonl.1').exists())
            self.assertLess(path.stat().st_size, 1024)
