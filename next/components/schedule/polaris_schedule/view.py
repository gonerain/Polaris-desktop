"""Owned Qt Quick resources and request-scoped UI access."""
import json
from pathlib import Path
import threading
import uuid
from PySide6.QtCore import QObject, Property, Signal, Slot, QThread, QUrl, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlEngine, qmlContext
from PySide6.QtQuick import QQuickItem
import shiboken6
from polaris_platform.protocol import PlatformError


class Dispatcher(QObject):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        app = QGuiApplication.instance()
        if app is None:
            raise PlatformError('gui_unavailable', '请先启动图形界面')
        self.requested.connect(self.execute)
        self.moveToThread(app.thread())

    @Slot(object)
    def execute(self, job):
        function, event, result = job
        try:
            result.append((True, function()))
        except Exception as error:
            result.append((False, error))
        finally:
            event.set()

    def run(self, function):
        if QThread.currentThread() == self.thread():
            return function()
        event, result = threading.Event(), []
        self.requested.emit((function, event, result))
        if not event.wait(15):
            raise PlatformError('gui_unavailable', '界面暂时没有响应')
        success, value = result[0]
        if not success:
            raise value
        return value


class Bridge(QObject):
    changed = Signal()
    errorChanged = Signal()

    def __init__(self, component, context, parent):
        super().__init__(parent)
        self._component, self._context = component, context
        self._data = '{}'
        self._read_error = ''
        self._operation_error = ''

    @Property(str, notify=changed)
    def dataJson(self):
        return self._data

    @Property(str, notify=errorChanged)
    def lastError(self):
        return '\n'.join(filter(None, (self._operation_error, self._read_error)))

    def _failure(self, error, operation=False):
        message = getattr(error, 'message', str(error))
        if operation:
            self._operation_error = message
        else:
            self._read_error = message
        self.errorChanged.emit()
        return False

    @Slot(result=bool)
    def refresh(self):
        try:
            data = self._context.call(self._component.port.id, 'get', {})
            self._data = json.dumps(data, ensure_ascii=False)
        except Exception as error:
            # A revoked read permission must not keep exposing the cached snapshot.
            self._data = '{}'
            self.changed.emit()
            return self._failure(error)
        self._read_error = ''
        self.changed.emit()
        self.errorChanged.emit()
        return True

    @Slot()
    def notified(self):
        self.refresh()

    @Slot(str, str, result=bool)
    def invoke(self, operation, payload):
        try:
            if operation not in self._component._handlers or operation in ('create_view', 'release_view'):
                raise ValueError('未知日程操作')
            params = json.loads(payload)
            if not isinstance(params, dict):
                raise ValueError('操作参数必须是对象')
            self._context.call(self._component.port.id, operation, params)
        except Exception as error:
            return self._failure(error, operation=True)
        self._operation_error = ''
        self.errorChanged.emit()
        QTimer.singleShot(0, self.notified)
        return True


class Presentation:
    def __init__(self, component):
        self.component = component
        self.closed = False
        self.dispatcher = Dispatcher()
        self._views = {}
        class Changes(QObject):
            changed = Signal()
        self.changes = Changes()
        self.changes.moveToThread(self.dispatcher.thread())
        self.changed = self.changes.changed

    def create(self, parent, ctx, owner):
        def valid():
            return not self.closed and self.component.port is owner and self.component._presentation is self
        def create():
            if not valid():
                raise PlatformError('stale_instance', '日程视图请求所属实例已经停止')
            engine = qmlEngine(parent)
            if engine is None:
                raise PlatformError('view_error', 'Native parent has no QML engine')
            context = QQmlContext(qmlContext(parent), parent)
            bridge = Bridge(self.component, ctx, context)
            bridge.refresh()
            self.changed.connect(bridge.notified, Qt.QueuedConnection)
            context.setContextProperty('scheduleModel', bridge)
            definition = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Schedule.qml'))))
            item = definition.create(context)
            if item is None or not isinstance(item, QQuickItem):
                error = '\n'.join(error.toString() for error in definition.errors())
                if item is not None:
                    item.deleteLater()
                context.deleteLater()
                definition.deleteLater()
                raise PlatformError('view_error', error or 'Schedule.qml must create a QQuickItem')
            context.setParent(item)
            item.setParentItem(parent)
            item.setParent(parent)
            definition.setParent(item)
            if not valid():
                item.setParentItem(None)
                item.deleteLater()
                raise PlatformError('stale_instance', '日程视图请求所属实例已经停止')
            handle = uuid.uuid4().hex
            self._views[handle] = (item, context, bridge, definition)
            item.destroyed.connect(lambda: self._views.pop(handle, None))
            return {'handle': handle, 'item': item}
        return self.dispatcher.run(create)

    def release(self, handle):
        def release():
            resource = self._views.pop(handle, None)
            if resource is None:
                return {'released': False}
            item, context, bridge, definition = resource
            if shiboken6.isValid(item):
                self.changed.disconnect(bridge.notified)
                item.setVisible(False)
                item.setParentItem(None)
                item.deleteLater()
            return {'released': True}
        return self.dispatcher.run(release)

    def close(self):
        def close():
            for handle in list(self._views):
                self.release(handle)
            self.changes.deleteLater()
        self.dispatcher.run(close)
        # Pending native requests retain this dispatcher until their stale check runs.
