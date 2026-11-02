from pathlib import Path
import uuid
from ..component import Component
from ..protocol import PlatformError
from .qt_ports import ResourceCleanupPort, NativeQtProfilePort


class Presentation(Component):
    source = ''
    resource_dir = Path(__file__).parent
    title = ''
    size = (640, 480)
    def __init__(self, runtime=None, window_id='window', cleanup_port=None):
        super().__init__()
        self._cleanup_host = ResourceCleanupPort(runtime, window_id) if runtime is not None else cleanup_port
        self.window_id = window_id
        self._qt_profile_port = NativeQtProfilePort(runtime, window_id) if runtime is not None else None
        self.qt_context = {}
        self.window_options = {}
        self.handle = None
        self.running = False
        self._presentation_generation = uuid.uuid4().hex
        self.properties = {}
        self._view_state = {'available': False, 'visible': False}
        self.views = [{'id': 'main', 'title': self.title, 'adapter': 'qt-quick', 'actions': [
            {'label': '显示', 'operation': 'show', 'permissions': [{'target': window_id, 'name': name} for name in ('status', 'create', 'show')]},
            {'label': '隐藏', 'operation': 'hide', 'permissions': [{'target': window_id, 'name': 'hide'}]}]}]
        self.dependencies = [{'target': window_id, 'kind': 'capability', 'operations': ['show', 'hide']}]
        self.operation('status')(lambda p, c: self.status(c))
        self.operation('show', 'write')(lambda p, c: self.show(c))
        self.operation('hide', 'write')(lambda p, c: self.hide(c))

    def describe(self):
        result = super().describe()
        result['view_state'] = dict(self._view_state)
        return result

    def start(self, port):
        super().start(port)
        self.running = True
        self._presentation_generation = uuid.uuid4().hex

    def stop(self):
        self.running = False
        self._presentation_generation = uuid.uuid4().hex
        if self._cleanup_host and self.handle and self.port:
            self._cleanup_host.release_owned(self.port.id, self.handle)
        if self._qt_profile_port and self.port:
            self._qt_profile_port.unregister(self.port)
        self.handle = None
        self.running = False
        self._view_state = {'available': False, 'visible': False}
        super().stop()

    def _window(self, operation, params, context):
        if self.port is None:
            raise PlatformError('component_unavailable', '组件未运行')
        return self.port.call(self.window_id, operation, params, context=context)

    def status(self, context=None):
        if context is not None:
            state = self._window('status', {'handle': self.handle}, context)
            self._view_state = dict(state)
        return dict(self._view_state, running=self.running)

    def show(self, context=None, params=None):
        if not self.running or self.port is None:
            raise PlatformError('component_unavailable', '组件未运行')
        generation, owner = self._presentation_generation, self.port.id
        state = self._window('status', {'handle': self.handle}, context)
        if not self.handle or not state.get('available'):
            if self.qt_context:
                if self._qt_profile_port is None:
                    raise PlatformError('native_profile_unavailable', '组件未配置原生界面接入')
                self._qt_profile_port.register(self.port, self.qt_context)
            result = self._window('create', {'source': str(self.resource_dir / self.source), 'title': self.title,
                    'size': list(self.size), 'properties': self.properties, 'options': self.window_options}, context)
            if not self.running or generation != self._presentation_generation:
                if self._cleanup_host:
                    self._cleanup_host.release_owned(owner, result['handle'])
                raise PlatformError('stale_instance', '展示请求所属实例已经停止')
            self.handle = result['handle']
            self._view_state = self._window('status', {'handle': self.handle}, context)
        else:
            self._view_state = self._window('show', {'handle': self.handle}, context)
        return dict(self._view_state, running=self.running)

    def hide(self, context=None):
        if self.handle:
            self._view_state = self._window('hide', {'handle': self.handle}, context)
        return dict(self._view_state, running=self.running)
