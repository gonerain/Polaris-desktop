"""Application-owned QtQuick scene, isolated from the canvas QML context."""
import shiboken6
from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl
from PySide6.QtQml import QQmlEngine, QQmlComponent, QQmlContext
from PySide6.QtQuick import QQuickItem
from ..protocol import PlatformError


class AppCapabilityBridge(QObject):
    changed = Signal()
    completed = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, host, application_id):
        super().__init__()
        self.host = host
        self.application_id = application_id
        self.enabled = False
        self.generation = 0

    @Property(bool, notify=changed)
    def active(self):
        return self.enabled

    def set_active(self, active):
        if self.enabled != bool(active):
            self.enabled = bool(active)
            self.generation += 1
            self.changed.emit()

    @Slot(str, 'QVariantMap', str)
    def call(self, alias, params, request_id):
        try:
            if not self.enabled:
                raise PlatformError('application_inactive', '请先打开此应用')
            self.host.call_alias(self, alias, params, request_id)
        except Exception as error:
            self.failed.emit(request_id, str(error))

    def deliver(self, generation, request_id, result, error):
        if self.enabled and self.generation == generation:
            if error:
                self.failed.emit(request_id, error)
            else:
                self.completed.emit(request_id, result)


class AppBackendBridge(QObject):
    changed = Signal()
    completed = Signal(str, str)
    failed = Signal(str, str)
    delivered = Signal(object, str, str, str)

    def __init__(self, host, application_id):
        super().__init__()
        self.host, self.application_id = host, application_id
        self.enabled = False
        host.changed.connect(self.changed)
        self.delivered.connect(self._deliver)

    @Property(bool, notify=changed)
    def available(self):
        return self.host._backend_available(self.application_id)

    @Property(bool, notify=changed)
    def running(self):
        runner = self.host._backends.get(self.application_id)
        return bool(runner and runner.running)

    @Property(bool, notify=changed)
    def stopping(self):
        runner = self.host._backends.get(self.application_id)
        return bool(runner and runner.stopping)

    @Property(str, notify=changed)
    def error(self):
        runner = self.host._backends.get(self.application_id)
        return self.host._backend_errors.get(self.application_id, '') or (runner.error if runner else '')

    @Property(str, notify=changed)
    def warningsJson(self):
        import json
        return json.dumps(self.host._backend_warnings.get(self.application_id, []), ensure_ascii=False)

    @Property(str, notify=changed)
    def stateJson(self):
        import json
        runner = self.host._backends.get(self.application_id)
        return json.dumps(runner.state if runner else {}, ensure_ascii=False)

    @Slot()
    def start(self):
        try:
            if not self.enabled:
                raise PlatformError('application_inactive', '请先打开此应用界面')
            self.host.start_backend(self.application_id)
        except Exception as error:
            self.host._backend_errors[self.application_id] = str(error)
            self.changed.emit()

    @Slot()
    def stop(self):
        try:
            if not self.enabled:
                raise PlatformError('application_inactive', '请先打开此应用界面')
            self.host.stop_backend(self.application_id)
        except Exception as error:
            self.host._backend_errors[self.application_id] = str(error)
            self.changed.emit()

    @Slot(str, 'QVariantMap', str)
    def call(self, command, params, request_id):
        try:
            self.host.backend_call(self, command, params, request_id)
        except Exception as error:
            self.failed.emit(request_id, str(error))

    @Slot(object, str, str, str)
    def _deliver(self, runner, request_id, result, error):
        if self.enabled and self.host._backends.get(self.application_id) is runner and not runner.context.stopped.is_set():
            if error:
                self.failed.emit(request_id, error)
            else:
                self.completed.emit(request_id, result)


class ApplicationView:
    def __init__(self, host, application, entry, parent):
        self._closed = False
        self._connected = False
        self.application_id = application.id
        self.parent = parent
        self.bridge = AppCapabilityBridge(host, application.id)
        self.backend_bridge = AppBackendBridge(host, application.id)
        self.engine = QQmlEngine()
        storage = host.application_data_directory(application.id) / 'qml-storage'
        storage.mkdir(parents=True, exist_ok=True)
        self.engine.setOfflineStoragePath(str(storage))
        self.context = QQmlContext(self.engine.rootContext())
        self.context.setContextProperty('appCapabilities', self.bridge)
        self.context.setContextProperty('appBackend', self.backend_bridge)
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(entry)))
        self.root = self.component.create(self.context)
        if not isinstance(self.root, QQuickItem):
            errors = '; '.join(error.toString() for error in self.component.errors())
            self.close()
            raise PlatformError('application_ui_failed', errors or '应用入口必须创建QtQuick Item')
        self.root.destroyed.connect(self._root_destroyed)
        self.root.setParent(parent)
        self.root.setParentItem(parent)
        parent.widthChanged.connect(self.resize)
        parent.heightChanged.connect(self.resize)
        self._connected = True
        self.resize()

    def _root_destroyed(self):
        self.root = None
        self.bridge.set_active(False)
        self.backend_bridge.enabled = False

    def resize(self):
        if (not self._closed and self.root is not None and shiboken6.isValid(self.root)
                and shiboken6.isValid(self.parent)):
            self.root.setWidth(self.parent.width())
            self.root.setHeight(self.parent.height())

    def set_active(self, active):
        self.bridge.set_active(active)
        self.backend_bridge.enabled = bool(active)
        if self.root is not None and shiboken6.isValid(self.root):
            self.root.setVisible(bool(active))

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.bridge.set_active(False)
        self.backend_bridge.enabled = False
        if self._connected and shiboken6.isValid(self.parent):
            try:
                self.parent.widthChanged.disconnect(self.resize)
                self.parent.heightChanged.disconnect(self.resize)
            except (RuntimeError, TypeError):
                pass
        root = getattr(self, 'root', None)
        self.root = None
        if root is not None and shiboken6.isValid(root):
            if isinstance(root, QQuickItem):
                root.setParentItem(None)
            root.deleteLater()
        for resource in (self.backend_bridge, self.context, self.component, self.engine):
            if shiboken6.isValid(resource):
                resource.deleteLater()
