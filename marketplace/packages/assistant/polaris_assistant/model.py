"""Small, bounded chat-completion transport, independent of the UI."""
import json
import os
from pathlib import Path
import socket
import threading
import time
import urllib.request
import urllib.error
import uuid
from .usage import UsageLog, token_usage


MODEL_TIMEOUT = 180
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ModelError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


PROFILES = {
    'deepseek': ('DeepSeek', 'deepseek-flash', 'DEEPSEEK_API_KEY', 'https://api.deepseek.com/chat/completions'),
    'bigmodel': ('GLM', 'glm-5.3-flash', 'ZHIPUAI_API_KEY', 'https://open.bigmodel.cn/api/paas/v4/chat/completions'),
    'zai': ('GLM', 'glm-5.3-flash', 'ZAI_API_KEY', 'https://api.z.ai/api/paas/v4/chat/completions'),
}


def _settings(directory):
    if directory is not None:
        path = Path(directory) / 'model.json'
        if path.exists():
            try:
                if path.stat().st_size > 4096:
                    raise ValueError()
                data = json.loads(path.read_text('utf8'))
                if not isinstance(data, dict) or data.get('version') != 1 or 'provider' not in data:
                    raise ValueError()
                return data
            except (OSError, ValueError, KeyError, TypeError):
                raise ModelError('模型服务设置无法读取，请检查 model.json') from None
    return {}


def selected_provider(directory=None):
    provider = os.environ.get('POLARIS_AGENT_MODEL_PROVIDER', '').strip().lower()
    if not provider:
        provider = _settings(directory).get('provider')
    provider = provider or 'deepseek'
    if not isinstance(provider, str) or provider not in PROFILES:
        raise ModelError('模型服务必须为 deepseek、bigmodel 或 zai')
    return provider


def configured_model(directory=None):
    provider = selected_provider(directory)
    effort = _settings(directory).get('reasoning_effort')
    key = None
    if directory is not None and not os.environ.get(PROFILES[provider][2], '').strip():
        path = Path(directory) / (provider + '-api-key')
        if path.exists():
            try:
                if path.stat().st_size > 4096:
                    raise ValueError()
                key = path.read_text('utf8').strip()
            except (OSError, ValueError):
                raise ModelError('模型密钥文件无法读取') from None
    return ChatModel(key, provider=provider, reasoning_effort=effort,
                     usage_path=Path(directory) / 'model-usage.jsonl' if directory is not None else None)


class ChatModel:
    def __init__(self, api_key=None, opener=None, *, provider='deepseek', usage_path=None, reasoning_effort=None):
        if provider not in PROFILES:
            raise ModelError('模型服务配置无效')
        self.accounting = UsageLog(usage_path)
        self.local = threading.local()
        self.provider = provider
        self.reasoning_effort = reasoning_effort if reasoning_effort is not None else ('max' if provider == 'deepseek' else 'low')
        if self.reasoning_effort not in ('low', 'high', 'max'):
            raise ModelError('reasoning_effort 必须为 low、high 或 max')
        self.label, self.model_id, self.key_env, self.endpoint = PROFILES[provider]
        self._key = os.environ.get(self.key_env, '') if api_key is None else api_key
        if isinstance(self._key, str):
            self._key = self._key.strip()
        if (not isinstance(self._key, str) or not 8 <= len(self._key) <= 4096
                or any(not 33 <= ord(char) <= 126 for char in self._key)):
            raise ModelError('请配置有效的 ' + self.key_env)
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    def begin_run(self):
        self.local.run_id = uuid.uuid4().hex
        self.local.sequence = 0

    def redact(self, value):
        return str(value).replace(self._key, '[已隐藏密钥]')

    def complete(self, messages, tools, cancel, timeout=MODEL_TIMEOUT, tool_choice=None):
        if cancel.is_set():
            raise ModelError('请求已取消')
        payload = {'model': self.model_id, 'messages': messages,
                   'thinking': {'type': 'enabled'}, 'reasoning_effort': self.reasoning_effort, 'stream': False, 'max_tokens': 4096}
        if self.provider != 'deepseek':
            payload['thinking']['clear_thinking'] = False
        if tools:
            payload['tools'] = tools
        if tool_choice is not None:
            payload['tool_choice'] = tool_choice
        body = json.dumps(payload, ensure_ascii=False).encode()
        if not getattr(self.local, 'run_id', None):
            self.begin_run()
        self.local.sequence += 1
        audit = dict(runId=self.local.run_id, sequence=self.local.sequence, phase=getattr(self.local, 'phase', 'generate'),
                     provider=self.provider, requestedModel=self.model_id, reasoningEffort=payload['reasoning_effort'],
                     requestBytes=len(body), messageCount=len(messages),
                     toolResultChars=sum(len(m.get('content', '')) for m in messages if m.get('role') == 'tool' and isinstance(m.get('content'), str)),
                     status='error')
        audit_started = time.monotonic()
        request = urllib.request.Request(self.endpoint,
            data=body,
            headers={'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json'})
        deadline = time.monotonic() + timeout
        response = None
        finished = threading.Event()
        def watch():
            while not finished.wait(.05):
                if cancel.is_set() or time.monotonic() >= deadline:
                    if response is not None:
                        response.close()
                    return
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            response = self._opener.open(request, timeout=max(.1, timeout))
            data = bytearray()
            while True:
                if cancel.is_set() or time.monotonic() >= deadline:
                    raise ModelError('请求已取消或超时')
                block = response.read(16384)
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ModelError('模型响应过大')
            if cancel.is_set() or time.monotonic() >= deadline:
                raise ModelError('请求已取消或超时')
            decoded = json.loads(data)
            actual_model = decoded.get('model')
            audit.update(status='ok', usage=token_usage(decoded), responseBytes=len(data))
            if isinstance(actual_model, str):
                audit['responseModel'] = self.redact(actual_model)[:128]
            response_id = decoded.get('id')
            if isinstance(response_id, str):
                audit['responseId'] = self.redact(response_id)[:128]
            message = decoded['choices'][0]['message']
            if not isinstance(message, dict):
                raise ValueError()
            content = message.get('content')
            if content is not None and not isinstance(content, str):
                raise ModelError('模型正文格式无效')
            reasoning = message.get('reasoning_content')
            if reasoning is not None and not isinstance(reasoning, str):
                raise ModelError('模型思考格式无效')
            audit.update(reasoningChars=len(reasoning or ''), replyChars=len(content or ''))
            calls = message.get('tool_calls', [])
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise ModelError('模型工具响应格式无效')
            result = {'role': 'assistant', 'content': self.redact(content) if content is not None else None}
            # Thinking is transient tool-loop context, never user-visible history.
            if reasoning is not None:
                result['reasoning_content'] = self.redact(reasoning)
            if calls:
                normalized = []
                for call in calls:
                    if not isinstance(call, dict) or not isinstance(call.get('function'), dict):
                        raise ModelError('模型工具响应格式无效')
                    function = call['function']
                    if (not isinstance(call.get('id'), str) or not isinstance(function.get('name'), str)
                            or not isinstance(function.get('arguments'), str)):
                        raise ModelError('模型工具响应格式无效')
                    normalized.append({'id': call['id'], 'type': 'function', 'function': {
                        'name': function['name'], 'arguments': function['arguments']}})
                result['tool_calls'] = json.loads(self.redact(json.dumps(normalized)))
            return result
        except ModelError:
            raise
        except urllib.error.HTTPError as exc:
            audit['httpStatus'] = exc.code
            raise ModelError(f'{self.label} 请求失败（HTTP {exc.code}）') from None
        except (TimeoutError, socket.timeout):
            raise ModelError(self.label + ' 请求超时') from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ModelError(self.label + ' 请求超时') from None
            raise ModelError(self.label + ' 请求失败，请检查网络或配置') from None
        except Exception:
            if cancel.is_set() or time.monotonic() >= deadline:
                raise ModelError('请求已取消或超时') from None
            # Network exceptions can contain headers or response bodies; never expose them.
            raise ModelError(self.label + ' 请求失败，请检查网络或配置') from None
        finally:
            audit['durationSeconds'] = round(time.monotonic() - audit_started, 3)
            self.accounting.append(audit)
            finished.set()
            if response is not None:
                response.close()


class DeepSeek(ChatModel):
    """Explicit DeepSeek transport for existing callers."""
    pass
