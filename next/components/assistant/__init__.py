"""Polaris Agent: conversational model and authorized tool execution."""
from collections import OrderedDict
import json
import threading
import uuid

from polaris_platform.protocol import PlatformError, capability
from polaris_platform.sdk import Component
from .loop import AgentLoop, AgentResult
from .model import DeepSeek, ModelError
from .tools import ToolExecutor, operations


class _Turn:
    """Optional caller-owned lease; the model cannot choose its callback address."""
    def __init__(self, ctx, caller, control, turn, stopped):
        self.ctx, self.caller, self.control, self.turn, self.stopped = ctx, caller, control, turn, stopped

    def is_set(self):
        if self.stopped.is_set():
            return True
        if self.control:
            try:
                result = self.ctx.call(self.caller, self.control, {'turn': self.turn, 'action': 'active'})
                return result.get('active') is not True
            except Exception:
                return True
        return False

    def prepare(self, target, metadata, arguments):
        if not self.control or metadata.get('completionCallback') != {'version': 1, 'parameter': 'on_complete'}:
            return arguments
        return self.ctx.call(self.caller, self.control, dict(turn=self.turn, action='prepare', target=target,
                                                              metadata=metadata, arguments=arguments))


class Assistant(Component):
    def __init__(self, engine=None, directory_id='collaboration'):
        super().__init__()
        self.engine, self.directory_id = engine, directory_id
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._conversations = OrderedDict()
        self._busy = set()
        self.presentation = None
        self.views = [dict(id='main',title='Polaris Agent',adapter='qt-quick-item',create='create_view',
                           release='release_view', permissions=[dict(name='reply', access='write'),
                           dict(target=directory_id, name='discover', access='read'),
                           dict(target=directory_id, name='describe', access='read')])]
        self.operation('create_view', access='write')(self.create_view)
        self.operation('release_view', access='write')(self.release_view)
        self.operation('status', provides='polaris.agent.status@1')(self.status)
        self.operation('reply', access='write', provides='polaris.agent.reply@1')(self.reply)

    def describe(self):
        result = super().describe()
        result['operations']['reply'] = dict(result['operations']['reply'], title='对话',
            description='发送一条消息，可按会话继续对话；仅在本次委托和当前授权范围内使用工具。',
            parameters={'type':'object', 'required':['text'], 'properties':{
                'text':{'type':'string'},'conversation':{'type':'string'},'allowed':{'type':'array'}}})
        for name in ('create_view', 'release_view'):
            result['operations'][name] = dict(result['operations'][name], profile='qt-native')
        return result

    def create_view(self, view, parent, ctx):
        if view != 'main':
            raise PlatformError('missing_view', view)
        with self._lock:
            if self._stopped.is_set():
                raise PlatformError('stale_instance', 'Polaris Agent 已停止')
            if self.presentation is None:
                from .view import Presentation
                self.presentation = Presentation(self)
            presentation = self.presentation
        return presentation.create(parent, ctx)

    def release_view(self, handle):
        return self.presentation.release(handle) if self.presentation else {'released': False}

    def start(self, port):
        super().start(port)
        self._stopped = threading.Event()

    def stop(self):
        with self._lock:
            self._stopped.set()
            self._conversations.clear()
            presentation, self.presentation = self.presentation, None
        if presentation:
            presentation.close()
        super().stop()

    def status(self):
        with self._lock:
            if self.engine is None:
                try:
                    self.engine = AgentLoop(DeepSeek())
                except ModelError as error:
                    return dict(ready=False, model='deepseek-flash', detail=str(error))
            return dict(ready=True, model='deepseek-flash', detail='')

    def _authorized_tools(self, ctx):
        records = ctx.call(self.directory_id, 'discover', {}).get('components', [])
        return [dict(target=record['id'], operation=name) for record in records
                if record['id'] not in (self.port.id, ctx.context.caller, self.directory_id)
                for name, meta in operations(record).items()
                if capability(record['installation'], 'operation', name, meta) in ctx.context.scope]

    def reply(self, text, ctx, conversation='main', parent=None, turn=None, allowed=None, control=None, use_authorized_tools=False, max_reply_chars=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise PlatformError('invalid_params', '请输入 1–8000 字的消息')
        turn = uuid.uuid4().hex if turn is None else turn
        if any(not isinstance(s, str) or not 0 < len(s) <= 128 for s in (conversation, turn)):
            raise PlatformError('invalid_params', '无效的会话或轮次')
        if parent is not None and (not isinstance(parent, str) or len(parent) > 128):
            raise PlatformError('invalid_params', '无效的上轮标识')
        if type(use_authorized_tools) is not bool or use_authorized_tools and allowed is not None:
            raise PlatformError('invalid_params', '请选择一种工具范围')
        if use_authorized_tools:
            allowed = self._authorized_tools(ctx)
        if allowed is None:
            allowed = []
        if (not isinstance(allowed, list) or len(allowed) > 100 or any(not isinstance(row, dict)
                or set(row) != {'target','operation'} or not all(isinstance(v, str) and v for v in row.values()) for row in allowed)):
            raise PlatformError('invalid_params', '工具范围无效')
        if control is not None and (not isinstance(control, str) or not control or len(control) > 128):
            raise PlatformError('invalid_params', '回调操作无效')
        if max_reply_chars is not None and (type(max_reply_chars) is not int or max_reply_chars < 16):
            raise PlatformError('invalid_params', '回复长度无效')
        state = self.status()
        if not state['ready']:
            raise PlatformError('invalid_state', state['detail'])
        origin = ctx.context
        caller = origin.caller
        key = (origin.origin_installation, caller, conversation)
        lease = _Turn(ctx, caller, control, turn, self._stopped)
        with self._lock:
            if key in self._busy:
                raise PlatformError('busy', '该会话正在回复')
            snapshots = self._conversations.get(key, {})
            if turn in snapshots:
                raise PlatformError('duplicate_turn', '本轮已处理')
            # Channels supply the last delivered turn. A fresh provider starts without history.
            history = (next(reversed(snapshots.values())) if parent is None and snapshots else snapshots.get(parent, []))
            self._busy.add(key)
        try:
            allowed = [row for row in allowed if row['target'] not in (caller, self.port.id, self.directory_id)]
            tools = ToolExecutor(ctx, allowed, self.directory_id, self.port.id, lease, caller)
            try:
                result = self.engine.run(text, history, tools, lease)
            except ModelError as exc:
                safe = getattr(self.engine, '_safe', str)
                reply = tools.failure_reply(safe(exc))
                result = AgentResult(reply, [{'role':'user', 'content':safe(text)}, {'role':'assistant', 'content':reply}])
            if lease.is_set():
                raise PlatformError('cancelled', '本轮已取消')
            if max_reply_chars is not None and len(result.text) > max_reply_chars:
                suffix = '\n（内容较长，已截短）'
                result.text = result.text[:max_reply_chars-len(suffix)] + suffix
                if result.history and result.history[-1].get('role') == 'assistant':
                    result.history[-1]['content'] = result.text
            updated = (history + result.history)[-12:]
            while len(json.dumps(updated, ensure_ascii=False)) > 16000 and updated:
                updated = updated[2:]
            with self._lock:
                if lease.stopped.is_set():
                    raise PlatformError('cancelled', '组件已停止')
                previous = {parent: history} if parent and parent in snapshots else {}
                self._conversations[key] = {**previous, turn: updated}
                self._conversations.move_to_end(key)
                while len(self._conversations) > 128:
                    self._conversations.popitem(last=False)
            return {'text':result.text, 'turn':turn}
        finally:
            with self._lock:
                self._busy.discard(key)


def create():
    return Assistant()
