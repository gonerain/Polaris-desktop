"""Independent Agent component with an optional native Qt presentation."""
import os
import sys
import threading
from pathlib import Path
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from .model import AgentStore
from .bridge import Bridge
from .completion import Completions
import uuid


def default_data_dir():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') if os.name == 'nt' else Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'polaris-agent'


class Agent(Component):
    def __init__(self, data_dir=None):
        super().__init__()
        directory = Path(data_dir or default_data_dir())
        self.store = AgentStore(directory / 'agent.json')
        self._lock = self.store.lock
        self._presentation = None
        self._gui_stop = threading.Event()
        self._gui_dispatcher = None
        self._bridge_dir = directory / 'bridge'
        self.bridge = None
        self.completions = None
        self.store.listeners.append(self._changed)
        for name in ('get', 'sessions', 'status', 'result', 'delivery'):
            self.operation(name)(getattr(self, name))
        for name in ('mark', 'unmark', 'send', 'create_view', 'release_view'):
            self.operation(name, access='write')(getattr(self, name))
        self.views = [{'id': 'main', 'adapter': 'qt-quick-item', 'title': 'Agent',
            'create': 'create_view', 'release': 'release_view', 'permissions':
            [{'name': n, 'access': 'read'} for n in ('get', 'status', 'result', 'delivery')] +
            [{'name': n, 'access': 'write'} for n in ('mark', 'unmark', 'send')]}]

    def start(self, port):
        super().start(port)
        try:
            self.bridge = Bridge(self.store, self._bridge_dir)
            self.completions = Completions(self)
            self.completions.start()
            self._gui_stop = threading.Event()
            threading.Thread(target=self._watch_gui, args=(self._gui_stop,), daemon=True).start()
        except Exception:
            if self.bridge:
                self.bridge.close()
            super().stop()
            raise

    def _watch_gui(self, stopped):
        # Autostart can precede desktop imports and QApplication construction.
        # Only observe loaded Qt; a headless component never imports it.
        while not stopped.wait(.1):
            qtgui = sys.modules.get('PySide6.QtGui')
            if qtgui is None or qtgui.QGuiApplication.instance() is None:
                continue
            from .view import Dispatcher
            dispatcher = Dispatcher()
            self._gui_dispatcher = dispatcher
            dispatcher.post(lambda: self._ensure_presentation(stopped))
            return

    def _ensure_presentation(self, stopped):
        if stopped.is_set() or stopped is not self._gui_stop or self.port is None:
            return
        with self._lock:
            if self._presentation is None:
                from .view import Presentation
                self._presentation = Presentation(self)
            self._changed()

    def _changed(self):
        if self._presentation is not None:
            self._presentation.changed.emit()
            while self.store.notices:
                session, run = self.store.notices.pop(0)
                self._presentation.show_notice(session, run)
        else:
            self.store.notices[:] = self.store.notices[-100:]

    def get(self):
        import copy
        with self._lock:
            return {'sessions': self.sessions(), 'deliveries': copy.deepcopy(list(self.store.deliveries.values())),
                    'storageNotice': self.store.storage_notice}

    def sessions(self):
        return self.store.sessions()

    def status(self, session_id):
        return self.store.status(session_id)

    def result(self, session_id, run_id=None):
        return self.store.result(session_id, run_id)

    def delivery(self, delivery_id):
        return self.store.delivery(delivery_id)

    def mark(self, session_id):
        return self.store.mark(session_id)

    def unmark(self, session_id):
        return self.store.mark(session_id, False)

    def send(self, session_id, text, mode, delivery_id=None, on_complete=None, ctx=None):
        if self.bridge is None:
            raise ValueError('Agent bridge is not running')
        delivery_id = delivery_id or uuid.uuid4().hex
        with self.store.lock:
            existing = self.store.deliveries.get(delivery_id)
            if existing is not None and existing.get('onComplete') != on_complete:
                raise ValueError('deliveryId already used with another callback')
        callback = on_complete if existing is not None else self.completions.prepare(delivery_id, on_complete, ctx)
        return self.bridge.send(session_id, text, delivery_id, mode, on_complete=callback)

    def describe(self):
        result = super().describe()
        session = {'type': 'string', 'description': 'sessions 返回的完整 id 字段；不是 sessionId、标题或后缀。先列出会话，按用户描述匹配，再传入 id。'}
        specifications = {
            'get': ('查看概况', '返回会话和投递记录。', {}, []),
            'sessions': ('列出会话', '返回会话列表，包含 id、标题、在线状态和 marked。', {}, []),
            'status': ('查看会话状态', '返回指定会话详情。', {'session_id': session}, ['session_id']),
            'result': ('查看运行结果', '不指定 run_id 时返回该会话最近一次运行。',
                       {'session_id': session, 'run_id': {'type': 'string'}}, ['session_id']),
            'delivery': ('查看投递状态', '查询 send 返回的投递记录。pending=本机排队待确认；accepted=宿主已接收，仍不代表运行完成；rejected=宿主拒绝；unknown=结果未知。',
                         {'delivery_id': {'type': 'string'}}, ['delivery_id']),
            'mark': ('标记会话', '标记已有会话并返回会话记录；marked=true 表示标记成功。',
                     {'session_id': session}, ['session_id']),
            'unmark': ('取消标记', '取消会话标记并返回会话记录。', {'session_id': session}, ['session_id']),
            'send': ('发送消息', '仅向已标记、在线且 canSend=true 的会话提交消息。返回 pending 只表示已提交、等待宿主确认，不能说已送达或新一轮已开始；用 delivery 确认接收，再用 result 确认运行结果。',
                     {'session_id': session, 'text': {'type': 'string'},
                      'mode': {'type': 'string', 'enum': ['start', 'steer'], 'description': 'start 开始新一轮，steer 补充当前一轮。'},
                      'delivery_id': {'type': 'string', 'description': '可选的投递去重标识。'},
                      'on_complete': {'type':'object','description':'可选结果回传地址，由调用方适配器提供；不影响未配置回传的任务。'}}, ['session_id', 'text', 'mode']),
        }
        for name, (title, description, properties, required) in specifications.items():
            result['operations'][name] = dict(result['operations'][name], title=title, description=description,
                parameters={'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False})
        for name in ('create_view', 'release_view'):
            result['operations'][name] = dict(result['operations'][name], profile='qt-native')
        result['operations']['send']['completionCallback'] = {'version':1,'parameter':'on_complete'}
        return result

    def create_view(self, view, parent, ctx):
        if view != 'main':
            raise PlatformError('missing_view', view)
        if self.port is None:
            raise PlatformError('component_unavailable', 'Agent 组件未运行')
        if self._presentation is None:
            from .view import Presentation
            self._presentation = Presentation(self)
        return self._presentation.create(parent, ctx, self.port)

    def release_view(self, handle):
        return self._presentation.release(handle) if self._presentation else {'released': False}

    def stop(self):
        self._gui_stop.set()
        if self.completions:
            self.completions.stop()
            self.completions = None
        if self.bridge:
            self.bridge.close()
            self.bridge = None
        if self._presentation is not None:
            self._presentation.close()
            self._presentation = None
        super().stop()


def create(data_dir=None):
    return Agent(data_dir)
