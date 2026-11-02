"""Trusted native display ports shared by independent desktop components."""
import threading
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QGuiApplication
from ..protocol import PlatformError


class GuiDispatcher(QObject):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._execute)
        self.moveToThread(QGuiApplication.instance().thread())

    @Slot(object)
    def _execute(self, job):
        fn, event, box = job
        try:
            box.append((True, fn()))
        except Exception as exc:
            box.append((False, exc))
        finally:
            event.set()

    def run(self, fn):
        if QThread.currentThread() == self.thread():
            return fn()
        event, box = threading.Event(), []
        self.requested.emit((fn, event, box))
        if not event.wait(15):
            raise PlatformError('gui_unavailable', '界面暂时没有响应')
        ok, value = box[0]
        if not ok:
            raise value
        return value


class ResourceCleanupPort:
    """Trusted disposal-only binding; resolves the current native provider per use."""
    def __init__(self, runtime, target):
        self._runtime, self._target = runtime, target

    def release_owned(self, owner, handle):
        try:
            provider = self._runtime.component_instance(self._target)
        except PlatformError:
            return {'released': False}
        if provider is None:
            return {'released': False}
        return provider.release_owned(owner, handle)


class NativeQtProfilePort:
    """Native rendering binding. Window operations still use the authorized Client."""
    def __init__(self, runtime, target):
        self._runtime, self._target = runtime, target

    def register(self, client, bindings):
        provider = self._runtime.component_instance(self._target)
        if provider is None:
            raise PlatformError('window_unavailable', '窗口承载未运行')
        provider.register_qt_profile(client, bindings)

    def unregister(self, client):
        provider = self._runtime.component_instance(self._target)
        if provider is not None:
            provider.unregister_qt_profile(client)
