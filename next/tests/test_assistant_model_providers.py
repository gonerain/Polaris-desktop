import json
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/weixin'))
from components.assistant.model import ChatModel, ModelError, configured_model


class Response:
    def __init__(self, message):
        self.data = json.dumps({'choices': [{'message': message}]}).encode()
    def read(self, size):
        block, self.data = self.data[:size], self.data[size:]
        return block
    def close(self):
        pass


class Providers(unittest.TestCase):
    def test_glm_tool_loop_and_review_use_same_provider_without_exposing_key(self):
        class Opener:
            def __init__(self): self.requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                payload = json.loads(request.data)
                name = payload['tools'][0]['function']['name']
                args = {'needs_tools': False, 'reply': '已完成', 'reason': ''} if name == 'review_reply' else {'text': 'fixture-secret-key'}
                return Response({'reasoning_content': '思考', 'tool_calls': [
                    {'id': 'call1', 'function': {'name': name, 'arguments': json.dumps(args)}}]})
        opener = Opener()
        model = ChatModel('fixture-secret-key', opener, provider='bigmodel')
        result = model.complete([{'role': 'user', 'content': '查询'}],
            [{'type': 'function', 'function': {'name': 'lookup'}}], threading.Event())
        self.assertNotIn('fixture-secret-key', json.dumps(result))
        self.assertEqual(len(opener.requests), 1)
        for request in opener.requests:
            self.assertEqual(request.full_url, 'https://open.bigmodel.cn/api/paas/v4/chat/completions')
            body = json.loads(request.data)
            self.assertEqual(body['model'], 'glm-5.3-flash')
            self.assertEqual(body['thinking'], {'type': 'enabled', 'clear_thinking': False})
            self.assertEqual(body['reasoning_effort'], 'low')
            self.assertNotIn('tool_choice', body)

    def test_selection_requires_corresponding_key_and_keeps_deepseek_default(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'fake-deepseek-key'}, clear=True):
            self.assertEqual(configured_model().model_id, 'deepseek-flash')
            with patch.dict('os.environ', {'POLARIS_AGENT_MODEL_PROVIDER': 'bigmodel'}):
                with self.assertRaisesRegex(ModelError, 'ZHIPUAI_API_KEY'): configured_model()
            with patch.dict('os.environ', {'POLARIS_AGENT_MODEL_PROVIDER': 'zai', 'ZAI_API_KEY': 'fake-zai-key'}):
                model = configured_model()
                self.assertEqual(model.endpoint, 'https://api.z.ai/api/paas/v4/chat/completions')
                self.assertEqual(model._key, 'fake-zai-key')
            with patch.dict('os.environ', {'POLARIS_AGENT_MODEL_PROVIDER': 'typo'}):
                with self.assertRaises(ModelError): configured_model()

    def test_glm_http_failure_is_labelled_and_redacted(self):
        class Opener:
            def open(self, *args, **kwargs):
                raise urllib.error.HTTPError('https://open.bigmodel.cn', 503, 'fixture-secret-key', {}, None)
        with self.assertRaisesRegex(ModelError, '^GLM 请求失败（HTTP 503）$'):
            ChatModel('fixture-secret-key', Opener(), provider='bigmodel').complete([], [], threading.Event())

    def test_saved_provider_survives_restart_and_invalid_config_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {}, clear=True):
            root = Path(directory)
            (root / 'model.json').write_text('{"version":1,"provider":"bigmodel"}')
            (root / 'bigmodel-api-key').write_text('fixture-saved-key')
            first, restarted = configured_model(root), configured_model(root)
            self.assertEqual(first.provider, 'bigmodel')
            self.assertEqual(restarted._key, 'fixture-saved-key')
            (root / 'model.json').write_text('{"version":1,"provider":"bigmodel","reasoning_effort":"high"}')
            self.assertEqual(configured_model(root).reasoning_effort, 'high')
            (root / 'model.json').write_text('{"version":1,"provider":"bigmodel","reasoning_effort":"invalid"}')
            with self.assertRaisesRegex(ModelError, 'reasoning_effort'): configured_model(root)
            (root / 'model.json').write_text('broken')
            with self.assertRaisesRegex(ModelError, 'model.json'): configured_model(root)
