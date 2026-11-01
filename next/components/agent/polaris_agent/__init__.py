"""Independent Agent component with an optional native Qt presentation."""
import os
import sys
import threading
from pathlib import Path
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from .model import AgentStore
from .bridge import Bridge


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

    def send(self, session_id, text, mode, delivery_id=None):
        if self.bridge is None:
            raise ValueError('Agent bridge is not running')
        return self.bridge.send(session_id, text, delivery_id, mode)

    def describe(self):
        result = super().describe()
        for name in ('create_view', 'release_view'):
            result['operations'][name] = dict(result['operations'][name], profile='qt-native')
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
        if self.bridge:
            self.bridge.close()
            self.bridge = None
        if self._presentation is not None:
            self._presentation.close()
            self._presentation = None
        super().stop()


def create(data_dir=None):
    return Agent(data_dir)
