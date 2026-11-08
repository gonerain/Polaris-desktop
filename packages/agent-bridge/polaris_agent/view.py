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

    def post(self, function):
        """Queue GUI work without waiting for the GUI thread."""
        self.requested.emit((function, threading.Event(), []))

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
    pluginChanged = Signal()
    pluginFinished = Signal(object, object)

    def __init__(self, component, context, parent):
        super().__init__(parent)
        self._component, self._context = component, context
        self._data = '{}'
        self._read_error = ''
        self._operation_error = ''
        self._plugin_data = '{}'
        self._plugin_busy = False
        self.pluginFinished.connect(self._plugin_finished, Qt.QueuedConnection)

    @Property(str, notify=pluginChanged)
    def pluginJson(self):
        return self._plugin_data

    @Property(bool, notify=pluginChanged)
    def pluginBusy(self):
        return self._plugin_busy

    @Slot(object, object)
    def _plugin_finished(self, data, error):
        self._plugin_busy = False
        self._plugin_data = json.dumps(data if error is None else {'error': True, 'message': str(error)}, ensure_ascii=False)
        self.pluginChanged.emit()

    @Slot(bool, result=bool)
    def pluginAction(self, install=False):
        if self._plugin_busy:
            return False
        self._plugin_busy = True
        self._plugin_data = '{}'
        self.pluginChanged.emit()
        def execute():
            try:
                operation = 'codex_plugin_install' if install else 'codex_plugin_status'
                data = self._context.call(self._component.port.id, operation, {})
                error = None
            except Exception as failure:
                data, error = None, failure
            # A released view may finish after its QObject has been destroyed.
            try:
                if shiboken6.isValid(self):
                    self.pluginFinished.emit(data, error)
            except RuntimeError:
                pass  # QObject was released between the validity check and emit.
        threading.Thread(target=execute, daemon=True).start()
        return True

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
            if operation not in ('mark', 'unmark', 'send'):
                raise ValueError('未知Agent操作')
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
        self._notice = None
        presentation = self
        class Changes(QObject):
            changed = Signal()
            notice = Signal(object, object)

            @Slot(object, object)
            def present(self, session, run):
                presentation._show_notice(session, run)
        self.changes = Changes()
        self.changes.moveToThread(self.dispatcher.thread())
        self.changed = self.changes.changed
        self.changes.notice.connect(self.changes.present, Qt.QueuedConnection)

    def create(self, parent, ctx, owner):
        def valid():
            return not self.closed and self.component.port is owner and self.component._presentation is self
        def create():
            if not valid():
                raise PlatformError('stale_instance', 'Agent视图请求所属实例已经停止')
            engine = qmlEngine(parent)
            if engine is None:
                raise PlatformError('view_error', 'Native parent has no QML engine')
            context = QQmlContext(qmlContext(parent), parent)
            bridge = Bridge(self.component, ctx, context)
            bridge.refresh()
            self.changed.connect(bridge.notified, Qt.QueuedConnection)
            context.setContextProperty('agentModel', bridge)
            definition = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Agent.qml'))))
            item = definition.create(context)
            if item is None or not isinstance(item, QQuickItem):
                error = '\n'.join(error.toString() for error in definition.errors())
                if item is not None:
                    item.deleteLater()
                context.deleteLater()
                definition.deleteLater()
                raise PlatformError('view_error', error or 'Agent.qml must create a QQuickItem')
            context.setParent(item)
            item.setParentItem(parent)
            item.setParent(parent)
            definition.setParent(item)
            if not valid():
                item.setParentItem(None)
                item.deleteLater()
                raise PlatformError('stale_instance', 'Agent视图请求所属实例已经停止')
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
        self.closed = True
        def close():
            if self._notice is not None:
                self._notice.close()
                self._notice.deleteLater()
                self._notice = None
            for handle in list(self._views):
                self.release(handle)
            self.changes.deleteLater()
        self.dispatcher.run(close)
        # Pending native requests retain this dispatcher until their stale check runs.

    def show_notice(self, session, run):
        if not self.closed:
            self.changes.notice.emit(dict(session), dict(run))

    def _show_notice(self, session, run):
        if self.closed:
            return
        from PySide6.QtQuick import QQuickView
        if self._notice is None:
            self._notice = QQuickView()
            self._notice.setFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowStaysOnTopHint)
            self._notice.setColor(Qt.transparent)
            self._notice.setSource(QUrl.fromLocalFile(str(Path(__file__).with_name('AgentNotice.qml'))))
            self._notice_timer = QTimer(self.changes)
            self._notice_timer.setSingleShot(True)
            self._notice_timer.timeout.connect(self._notice.hide)
        statuses = {'completed': '已完成', 'failed': '失败', 'stopped': '已停止', 'unknown': '完成状态未知'}
        root = self._notice.rootObject()
        if root is None:
            return
        root.setProperty('noticeTitle', str(session.get('title') or session.get('sessionId') or 'Agent')[:120])
        root.setProperty('noticeState', '收到回复，完成状态未知' if run.get('status') == 'unknown' and run.get('reply')
                         else statuses.get(run.get('status'), '完成状态未知'))
        self._notice.resize(320, 86)
        screen = QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self._notice.setPosition(area.right() - 340, area.bottom() - 106)
        self._notice.show()
        self._notice_timer.start(6000)
