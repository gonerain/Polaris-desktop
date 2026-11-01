"""Local schedule capabilities; Qt is imported only when a view is requested."""
from pathlib import Path
import os
import threading
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from .model import ScheduleStore

WRITES = ('add', 'update', 'delete', 'undo_delete', 'add_subtask', 'update_subtask',
          'delete_subtask', 'reorder', 'move_overdue', 'organize_day')


def default_data_dir():
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'polaris-schedule'


class Schedule(Component):
    def __init__(self, data_dir=None):
        super().__init__()
        self.store = ScheduleStore(Path(data_dir or default_data_dir()) / 'schedule.json')
        self._lock = threading.RLock()
        self._presentation = None
        self.views = [{'id': 'main', 'adapter': 'qt-quick-item', 'title': '日程',
                       'create': 'create_view', 'release': 'release_view',
                       'permissions': [{'name': 'get', 'access': 'read'}] +
                                      [{'name': name, 'access': 'write'} for name in WRITES if name not in ('reorder', 'move_overdue', 'organize_day')]}]
        self.operation('get')(self.get)
        self.operation('tasks')(self.store.tasks)
        for name in WRITES:
            self.operation(name, access='write')(self._writer(name))
        self.operation('create_view', access='write')(self.create_view)
        self.operation('release_view', access='write')(self.release_view)

    def _writer(self, name):
        def write(**params):
            with self._lock:
                result = getattr(self.store, name)(**params)
                if self._presentation is not None:
                    self._presentation.changed.emit()
            return result
        return write

    def get(self):
        with self._lock:
            return {'tasks': self.store.tasks(), 'canUndo': self.store.can_undo,
                    'storageNotice': self.store.storage_notice}

    def describe(self):
        result = super().describe()
        for name in ('create_view', 'release_view'):
            result['operations'][name] = dict(result['operations'][name], profile='qt-native')
        return result

    def create_view(self, view, parent, ctx):
        if view != 'main':
            raise PlatformError('missing_view', view)
        with self._lock:
            owner = self.port
            if owner is None:
                raise PlatformError('component_unavailable', '日程组件未运行')
            if self._presentation is None:
                from .view import Presentation
                self._presentation = Presentation(self)
            presentation = self._presentation
        return presentation.create(parent, ctx, owner)

    def release_view(self, handle):
        return self._presentation.release(handle) if self._presentation else {'released': False}

    def stop(self):
        with self._lock:
            presentation, self._presentation = self._presentation, None
            if presentation is not None:
                presentation.closed = True
        if presentation is not None:
            presentation.close()
        super().stop()


def create(data_dir=None):
    return Schedule(data_dir)
