"""Local opt-in agent orchestration. Request authority lives only in memory."""
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
from polaris_platform.protocol import PlatformError
from .agent import WeixinAgent
from .model import DeepSeek, ModelError
from .storage import atomic_write


def operations(record):
    return {name: meta for name, meta in record.get('description', {}).get('operations', {}).items()
            if isinstance(meta, dict) and meta.get('available', True) and meta.get('profile') != 'qt-native'}


class ToolExecutor:
    def __init__(self, ctx, allowed, directory_id, own_id='weixin'):
        self.ctx, self.directory_id, self.own_id = ctx, directory_id, own_id
        self.allowed = {(r['target'], r['operation']) for r in allowed}
        self.explained = {}
        self.writes = {}

    def execute(self, name, args, cancel):
        if cancel.is_set():
            raise InterruptedError()
        if name == 'components':
            records = self.ctx.call(self.directory_id, 'discover', {}).get('components', [])
            filtered = [self.filtered(r) for r in records if any(t == r.get('id') for t, _ in self.allowed)]
            return {'components': [r for r in filtered if r['description']['operations']]}
        target = args.get('component')
        if target in (self.directory_id, self.own_id) or not any(t == target for t, _ in self.allowed):
            raise PlatformError('denied', '该操作未获微信自动回复允许')
        if name == 'help':
            record = self.filtered(self.ctx.call(self.directory_id, 'describe', {'target': target}))
            self.explained.update({(target, op): deepcopy(meta) for op, meta in record['description']['operations'].items()})
            return record
        if name != 'call':
            raise PlatformError('invalid_params', '未知工具')
        operation = args.get('operation')
        if (target, operation) not in self.allowed or (target, operation) not in self.explained:
            raise PlatformError('denied', '请先查询已允许操作的说明')
        arguments = args.get('arguments', {})
        if not isinstance(arguments, dict):
            raise PlatformError('invalid_params', '操作参数必须是对象')
        live = self.filtered(self.ctx.call(self.directory_id, 'describe', {'target': target}))
        metadata = live['description']['operations'].get(operation)
        if metadata != self.explained.get((target, operation)):
            raise PlatformError('stale_handle', '操作说明已改变，请重新查询帮助')
        if cancel.is_set():
            raise InterruptedError()
        if metadata.get('access') != 'write':
            return self.ctx.call(target, operation, arguments)
        key = (target, operation, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if key in self.writes:
            result, error = self.writes[key]
            if error:
                raise PlatformError('unknown_result', '该写操作已尝试，本轮不会重复提交')
            return deepcopy(result)
        self.writes[key] = (None, True)
        result = self.ctx.call(target, operation, arguments)
        self.writes[key] = (deepcopy(result), False)
        return result

    def filtered(self, record):
        return {'id': record.get('id'),
                'name': record.get('manifest', {}).get('name', record.get('id')),
                'description': {'operations': {n: deepcopy(m) for n, m in operations(record).items()
                                               if (record.get('id'), n) in self.allowed}}}



class AgentController:
    def __init__(self, client, path, changed, directory_id='collaboration', own_id='weixin', agent=None):
        self.client, self.path, self.changed = client, Path(path), changed
        self.directory_id, self.own_id = directory_id, own_id
        self.agent = agent
        self.has_key = agent is not None
        if agent is None:
            try:
                self.agent = WeixinAgent(DeepSeek())
                self.has_key = True
            except ModelError:
                pass
        self.lock = threading.RLock()
        self.enabled, self.busy, self.error = False, False, ''
        self.allowed, self.history, self.queue = [], [], deque()
        self.ctx, self.since = None, 0
        self.cancel = threading.Event()
        self.worker_running = False
        self.bad_file = False
        try:
            if self.path.exists():
                if self.path.stat().st_size > 100000:
                    raise ValueError()
                data = json.loads(self.path.read_text('utf8'))
                if not isinstance(data, dict) or data.get('version') != 1:
                    raise ValueError()
                self.allowed = self.validate(data['allowed'])
        except (OSError, ValueError, TypeError, KeyError, PlatformError):
            self.bad_file = True
            self.error = '自动回复设置无法读取，请修复或移走设置文件'

    def bind_identity(self, identity):
        with self.lock:
            self._cancel()
            self.own_id = identity
            # Settings created before the identity was known cannot authorize self calls.
            self.allowed = [r for r in self.allowed if r['target'] != identity]

    def validate(self, allowed):
        if not isinstance(allowed, list) or len(allowed) > 100:
            raise PlatformError('invalid_params', '请选择允许操作')
        rows = []
        for row in allowed:
            if not isinstance(row, dict) or set(row) != {'target', 'operation'} or any(not isinstance(row[k], str) or not row[k] or len(row[k]) > 256 for k in row):
                raise PlatformError('invalid_params', '允许操作格式无效')
            if row['target'] in (self.directory_id, self.own_id):
                raise PlatformError('denied', '请选择业务组件公开操作')
            if row not in rows:
                rows.append(dict(row))
        return rows

    def settings(self):
        with self.lock:
            return dict(enabled=self.enabled, busy=self.busy, error=self.error,
                        hasKey=self.has_key, model='deepseek-flash',
                        allowed=deepcopy(self.allowed), queued=len(self.queue))

    def catalog(self, ctx):
        records = ctx.call(self.directory_id, 'discover', {}).get('components', [])
        result = []
        for record in records:
            if record.get('id') in (self.directory_id, self.own_id):
                continue
            item = {'id': record.get('id'),
                    'name': record.get('manifest', {}).get('name', record.get('id')),
                    'description': {'operations': deepcopy(operations(record))}}
            if item['description']['operations']:
                result.append(item)
        return {'components': result}

    def configure(self, enabled, allowed, ctx):
        if not isinstance(enabled, bool):
            raise PlatformError('invalid_params', 'enabled 必须为布尔值')
        rows = self.validate(self.allowed if allowed is None else allowed)
        if enabled:
            catalog = self.catalog(ctx)
            available = {(r['id'], n) for r in catalog['components'] for n in r['description']['operations']}
            if any((r['target'], r['operation']) not in available for r in rows):
                raise PlatformError('invalid_params', '所选操作当前不可用')
            if self.agent is None:
                try:
                    self.agent = WeixinAgent(DeepSeek())
                    self.has_key = True
                except ModelError:
                    self.has_key = False
                    raise PlatformError('invalid_state', '请配置有效的 DEEPSEEK_API_KEY 后重新开启') from None
        with self.lock:
            if allowed is not None:
                if self.bad_file:
                    raise PlatformError('invalid_state', self.error)
                atomic_write(self.path, json.dumps({'version': 1, 'allowed': rows}, ensure_ascii=False).encode('utf8'))
                self.allowed = rows
            self._cancel()
            self.enabled, self.ctx, self.since = enabled, ctx if enabled else None, time.time()
            self.error = ''
        self.changed()
        return self.settings()

    def _cancel(self):
        self.cancel.set()
        self.cancel = threading.Event()
        self.enabled, self.ctx = False, None
        self.queue.clear()

    def invalidate(self):
        with self.lock:
            self._cancel()
        self.changed()

    def reset_conversation(self):
        with self.lock:
            self._cancel()
            self.history = []
        self.changed()

    def new_conversation(self):
        with self.lock:
            enabled, ctx = self.enabled, self.ctx
            self._cancel()
            self.history = []
            self.enabled, self.ctx, self.since = enabled, ctx, time.time()
            self.error = ''
        self.changed()
        return self.settings()

    def receive(self, text, timestamp):
        with self.lock:
            if not self.enabled or timestamp is None or not self.since <= timestamp <= time.time() + 300:
                return
            if len(self.queue) >= 3:
                self.error = '待回复消息已满，请重新开启自动回复'
                self._cancel()
            else:
                self.queue.append(text)
                if not self.worker_running:
                    self.worker_running = True
                    threading.Thread(target=self.run, daemon=True, name='weixin-agent').start()
        self.changed()

    def run(self):
        try:
            while True:
                with self.lock:
                    if not self.enabled or not self.queue:
                        return
                    text = self.queue.popleft()
                    cancel, ctx = self.cancel, self.ctx
                    allowed, history = deepcopy(self.allowed), deepcopy(self.history)
                    self.busy = True
                self.changed()
                try:
                    # Revalidate the initiating request before forwarding new text to the model.
                    ctx.call(self.own_id, 'get', {})
                    if cancel.is_set():
                        return
                    result = self.agent.run(text, history, ToolExecutor(ctx, allowed, self.directory_id, self.own_id), cancel)
                    # Manual and automatic sends share Client's one-flight sender.
                    while not cancel.is_set():
                        with self.client._lock:
                            if not self.client.sending:
                                if cancel.is_set():
                                    return
                                receipt = ctx.call(self.own_id, 'send', {'text': result.text})
                                break
                        cancel.wait(.05)
                    else:
                        return
                    while not cancel.wait(.05):
                        with self.client._lock:
                            row = next((r for r in self.client.messages if r['id'] == receipt['messageId']), None)
                            status = row['status'] if row else ''
                        if status != '发送中':
                            if status != '已发送':
                                raise RuntimeError('发送未确认，不会自动重发，请核实后重新开启')
                            with self.lock:
                                if not cancel.is_set():
                                    self.history.extend(result.history)
                                    self.history = self.history[-12:]
                                    while len(json.dumps(self.history, ensure_ascii=False)) > 16000 and self.history:
                                        del self.history[:2]
                            break
                except Exception:
                    with self.lock:
                        if not cancel.is_set():
                            self._cancel()
                            self.error = '自动回复失败或发送未确认，请检查授权与连接后重新开启'
                    return
                finally:
                    with self.lock:
                        self.busy = False
                    self.changed()
        finally:
            with self.lock:
                self.worker_running = False
                # A newly enabled epoch can queue while the previous worker unwinds.
                if self.enabled and self.queue:
                    self.worker_running = True
                    threading.Thread(target=self.run, daemon=True, name='weixin-agent').start()
