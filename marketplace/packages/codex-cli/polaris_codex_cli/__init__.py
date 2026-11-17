"""Instance-scoped Codex CLI component."""
import json
import os
from pathlib import Path
import threading
from copy import deepcopy
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from .transport import Transport


class CodexCLI(Component):
    def __init__(self, instance_context, transport_factory=Transport):
        super().__init__()
        self.instance_id = instance_context['instanceId']
        self.directory = Path(instance_context['dataDir'])
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'state.json'
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'cwd': '', 'threadId': None, 'turns': {}}
        for turn in self.data['turns'].values():
            if turn['status'] == 'running':
                turn['status'] = 'unknown'
        self.lock = threading.RLock()
        self.command_lock = threading.RLock()
        self.transport_factory = transport_factory
        self.transport = None
        self.connection = 'stopped'
        self.model_list = []
        self.default_model = None
        self.error = ''
        self.active = None
        self.active_context = None
        self.requests = {}
        self.presentation = None
        self.stopping = False
        self.views = [dict(id='main', title='Codex CLI', adapter='qt-quick-item', create='create_view', release='release_view', preferredSize=dict(width=760, height=600), permissions=[dict(name='get', access='read')])]
        for name in ('get', 'result'):
            self.operation(name, provides='polaris.codex-cli.' + name + '@1', applicationBinding='instance')(getattr(self, name))
        for name in ('configure', 'set_model', 'send', 'new', 'compact', 'interrupt'):
            self.operation(name, access='write', provides='polaris.codex-cli.' + name + '@1', applicationBinding='instance')(getattr(self, name))
        for name in ('respond', 'create_view', 'release_view'):
            self.operation(name, access='write')(getattr(self, name))
        self.event('turn.finished', provides='polaris.codex-cli.turn-finished@1')

    def describe(self):
        value = super().describe()
        schemas = {
            'get': ({}, []), 'result': ({'turn_id': {'type': 'string'}}, ['turn_id']),
            'configure': ({'cwd': {'type': 'string'}}, ['cwd']),
            'set_model': ({'model': {'type': 'string', 'description': '模型标识；空字符串使用 Codex 默认模型'}}, ['model']),
            'send': ({'text': {'type': 'string'}, 'mode': {'type': 'string', 'enum': ['start', 'steer']}}, ['text']),
            'new': ({}, []), 'compact': ({}, []), 'interrupt': ({}, []),
        }
        for name, (props, required) in schemas.items():
            value['operations'][name].update(title=name, parameters={'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False})
        value['operations']['respond'].update(humanOnly=True, modelCallable=False)
        for name in ('create_view', 'release_view'):
            value['operations'][name]['profile'] = 'qt-native'
        return value

    def _save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, self.path)

    def start(self, port):
        super().start(port)
        self.stopping = False
        if self.data['cwd']:
            threading.Thread(target=self._start_background, daemon=True).start()

    def _start_background(self):
        try:
            self._connect()
        except Exception as error:
            with self.lock:
                self.connection, self.error = 'error', str(error)

    def _connect(self):
        with self.command_lock:
            if self.stopping:
                raise PlatformError('stale_instance', '组件已停止')
            if self.transport:
                return
            if not self.data['cwd']:
                raise PlatformError('not_configured', '请先设置工作目录')
            with self.lock:
                self.connection, self.error = 'connecting', ''
            transport = self.transport_factory(self._message, self._exited)
            self.transport = transport
            try:
                models = []
                cursor = None
                while True:
                    response = transport.call('model/list', {'cursor': cursor})
                    models.extend(response['data'])
                    cursor = response.get('nextCursor')
                    if not cursor:
                        break
                config = transport.call('config/read', {'cwd': self.data['cwd']})['config']
                with self.lock:
                    self.model_list = [dict(model=m['model'], displayName=m['displayName'], isDefault=m['isDefault']) for m in models]
                    self.default_model = config.get('model') or next(m['model'] for m in models if m['isDefault'])
                if self.data['threadId'] and self.data.get('hasTurns', False):
                    transport.call('thread/resume', {'threadId': self.data['threadId'], 'cwd': self.data['cwd']})
                else:
                    result = transport.call('thread/start', {'cwd': self.data['cwd']})
                    with self.lock:
                        self.data['threadId'] = result['thread']['id']
                        self.data['hasTurns'] = False
                        self._save()
                with self.lock:
                    self.connection = 'ready'
            except Exception:
                self.transport = None
                transport.close()
                raise

    def stop(self):
        self.stopping = True
        if self.presentation:
            self.presentation.close()
            self.presentation = None
        with self.command_lock:
            transport, self.transport = self.transport, None
            if transport:
                transport.close()
        with self.lock:
            if self.active and self.active in self.data['turns']:
                self.data['turns'][self.active]['status'] = 'unknown'
                self._save()
            self.connection = 'stopped'
        super().stop()

    def _exited(self):
        with self.lock:
            if self.active and self.active in self.data['turns']:
                self.data['turns'][self.active]['status'] = 'unknown'
                self._save()
            self.active = None
            self.requests.clear()
            if not self.stopping:
                self.transport = None
                self.connection = 'error'
                self.error = 'Codex 进程退出，运行结果可能未知'

    def get(self):
        with self.lock:
            return dict(instanceId=self.instance_id, cwd=self.data['cwd'], threadId=self.data['threadId'], connection=self.connection, error=self.error, model=self.data.get('model', ''), defaultModel=self.default_model, models=deepcopy(self.model_list), activeTurnId=self.active, turns=deepcopy(list(self.data['turns'].values())), requests=deepcopy(list(self.requests.values())))

    def result(self, turn_id):
        with self.lock:
            return deepcopy(self.data['turns'].get(turn_id))

    def configure(self, cwd):
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
            raise PlatformError('invalid_params', '工作目录必须是存在的绝对目录')
        with self.command_lock:
            if self.active:
                raise PlatformError('busy', '请先结束当前回合')
            if cwd != self.data['cwd']:
                if self.transport:
                    transport, self.transport = self.transport, None
                    self.stopping = True
                    transport.close()
                    self.stopping = False
                with self.lock:
                    self.data['cwd'], self.data['threadId'], self.data['hasTurns'] = cwd, None, False
                    self._save()
            try:
                self._connect()
            except Exception as error:
                self.connection, self.error = 'error', str(error)
                raise
        return self.get()

    def set_model(self, model):
        if not isinstance(model, str):
            raise PlatformError('invalid_params', '模型标识必须是字符串')
        with self.command_lock:
            self._ready()
            if model and model not in {item['model'] for item in self.model_list}:
                raise PlatformError('invalid_params', '模型不在 Codex 返回的列表中')
            with self.lock:
                self.data['model'] = model
                self._save()
        return {'model': model, 'defaultModel': self.default_model}

    def _ready(self):
        if self.connection != 'ready' or not self.transport:
            raise PlatformError('unavailable', self.error or 'Codex 尚未就绪')

    def send(self, text, mode='start', ctx=None):
        if not isinstance(text, str) or not text.strip():
            raise PlatformError('invalid_params', '消息不能为空')
        if text.strip() == '/new': return self.new()
        if text.strip() == '/compact': return self.compact()
        if mode not in ('start', 'steer'):
            raise PlatformError('invalid_params', 'mode 必须为 start 或 steer')
        with self.command_lock:
            self._ready()
            if mode == 'start' and self.active:
                raise PlatformError('busy', '当前回合正在运行，请等待或使用 steer')
            if mode == 'steer' and not self.active:
                raise PlatformError('not_running', '没有可补充的回合')
            payload = {'threadId': self.data['threadId'], 'input': [{'type': 'text', 'text': text, 'text_elements': []}]}
            if mode == 'steer':
                payload['expectedTurnId'] = self.active
                self.transport.call('turn/steer', payload)
                return {'threadId': self.data['threadId'], 'turnId': self.active}
            payload['model'] = self.data.get('model') or self.default_model
            self.active_context = ctx
            reply = self.transport.call('turn/start', payload)
            turn_id = reply['turn']['id']
            with self.lock:
                if turn_id not in self.data['turns']:
                    self.data['turns'][turn_id] = {'threadId': self.data['threadId'], 'turnId': turn_id, 'status': 'running', 'reply': None, 'error': None}
                    self.active = turn_id
                self.data['turns'][turn_id]['message'] = text
                self.data['hasTurns'] = True
                self._save()
            return {'threadId': self.data['threadId'], 'turnId': turn_id}

    def new(self):
        with self.command_lock:
            self._ready()
            if self.active: raise PlatformError('busy', '请先结束当前回合')
            result = self.transport.call('thread/start', {'cwd': self.data['cwd']})
            with self.lock:
                self.data['threadId'] = result['thread']['id']
                self.data['hasTurns'] = False
                self._save()
            return {'threadId': self.data['threadId']}

    def compact(self):
        with self.command_lock:
            self._ready()
            if self.active: raise PlatformError('busy', '请先结束当前回合')
            self.transport.call('thread/compact/start', {'threadId': self.data['threadId']})
            return {'threadId': self.data['threadId'], 'accepted': True}

    def interrupt(self):
        with self.command_lock:
            self._ready()
            if not self.active: raise PlatformError('not_running', '没有运行中的回合')
            self.transport.call('turn/interrupt', {'threadId': self.data['threadId'], 'turnId': self.active})
            return {'turnId': self.active, 'accepted': True}

    def _message(self, message):
        method, params = message.get('method'), message.get('params', {})
        if 'id' in message and method:
            with self.lock:
                self.requests[str(message['id'])] = {'id': message['id'], 'method': method, 'params': params}
            return
        if method == 'turn/started' and params.get('threadId') == self.data['threadId']:
            turn_id = params['turn']['id']
            with self.lock:
                self.active = turn_id
                self.data['turns'].setdefault(turn_id, {'threadId': params['threadId'], 'turnId': turn_id, 'status': 'running', 'reply': None, 'error': None})
                self._save()
        elif method == 'item/completed' and params.get('threadId') == self.data['threadId']:
            item = params.get('item', {})
            if item.get('type') == 'agentMessage' and item.get('phase') in (None, 'final_answer'):
                with self.lock:
                    turn = self.data['turns'].get(params.get('turnId'))
                    if turn:
                        turn['reply'] = item.get('text')
                        self._save()
        elif method == 'turn/completed' and params.get('threadId') == self.data['threadId']:
            item = params['turn']; turn_id = item['id']
            with self.lock:
                turn = self.data['turns'].setdefault(turn_id, {'threadId': params['threadId'], 'turnId': turn_id, 'reply': None})
                turn.update(status=item['status'], error=item.get('error'))
                self.active = None
                self.requests.clear()
                self._save()
                event = dict(instanceId=self.instance_id, **deepcopy(turn))
                ctx, self.active_context = self.active_context, None
            if ctx:
                threading.Thread(target=lambda: ctx.publish('turn.finished', event), daemon=True).start()

    def respond(self, request_id, result, ctx=None):
        if ctx.context.source != 'user' or ctx.context.origin != self.port.id:
            raise PlatformError('permission_denied', '请在本机界面回答')
        with self.lock:
            request = self.requests[str(request_id)]
            self.transport.reply(request['id'], result)
            del self.requests[str(request_id)]
        return {'accepted': True}

    def create_view(self, view, parent, ctx):
        if view != 'main': raise PlatformError('missing_view', view)
        if self.presentation is None:
            from .ui import Presentation
            self.presentation = Presentation(self)
        return self.presentation.create(parent, ctx)

    def release_view(self, handle):
        return self.presentation.release(handle) if self.presentation else {'released': False}


def create(instance_context):
    return CodexCLI(instance_context)
