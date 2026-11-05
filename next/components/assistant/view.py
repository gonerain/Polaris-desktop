"""Local chat view. Model calls run off the GUI thread with the view's original context."""
from pathlib import Path
import json
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlContext, qmlEngine
from shiboken6 import isValid
from polaris_platform.protocol import PlatformError
from polaris_platform.desktop.qt_ports import GuiDispatcher


class Chat(QObject):
    answered = Signal(str, str)
    configurationChanged = Signal()
    settingsSaved = Signal(bool, str)

    def __init__(self, component, ctx, local_input, parent):
        super().__init__(parent)
        self.component, self.ctx = component, ctx
        self.local_input = local_input
        self.identity = component.port.id
        self.conversation = uuid.uuid4().hex
        self.closed = threading.Event()
        self._submission = threading.Lock()

    @Property(str, notify=configurationChanged)
    def configurationJson(self):
        return json.dumps(self.component.configuration_status(), ensure_ascii=False)

    @Slot()
    def refreshConfiguration(self):
        self.configurationChanged.emit()

    @Slot(str, str)
    def saveModel(self, provider, api_key):
        try:
            result = self.component.configure_from_view(self.local_input, provider, api_key)
        except PlatformError as error:
            self.settingsSaved.emit(False, error.message)
        except Exception:
            self.settingsSaved.emit(False, '模型设置未能保存，请重试')
        else:
            message = '已保存，可发送消息。发送时将连接模型服务。' if result['ready'] else '已保存。当前配置仍不可发送：' + result['detail']
            self.settingsSaved.emit(True, message)

    @Slot(str, bool)
    def submit(self, text, enable_tools=False):
        if self.closed.is_set() or not self._submission.acquire(blocking=False):
            return
        def work():
            try:
                try:
                    result = self.ctx.call(self.identity, 'reply', dict(text=text, conversation=self.conversation, use_authorized_tools=enable_tools))
                    reply, error = result['text'], ''
                except Exception as exc:
                    reply, error = '', str(exc)
            finally:
                self._submission.release()
            if not self.closed.is_set() and isValid(self):
                self.answered.emit(reply, error)
        thread = threading.Thread(target=work, daemon=True, name='polaris-agent-chat')
        try:
            thread.start()
        except Exception:
            self._submission.release()
            if not self.closed.is_set() and isValid(self):
                self.answered.emit('', '消息未能发送，请重试')


class Presentation:
    def __init__(self, component):
        self.component = component
        self.gui = GuiDispatcher()
        self.views = {}

    def create(self, parent, ctx):
        owner = self.component.port
        local_input = ctx.local_view_input(parent)
        def mount():
            if not owner or self.component.port is not owner:
                raise PlatformError('stale_instance', 'Polaris Agent 已停止')
            engine = qmlEngine(parent)
            if not engine:
                raise PlatformError('view_error', '没有 QML 引擎')
            scope = QQmlContext(qmlContext(parent), parent)
            chat = Chat(self.component, ctx, local_input, scope)
            scope.setContextProperty('assistantChat', chat)
            definition = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Chat.qml'))))
            item = definition.create(scope)
            if not item:
                scope.deleteLater()
                definition.deleteLater()
                raise PlatformError('view_error', '\n'.join(e.toString() for e in definition.errors()))
            scope.setParent(item)
            definition.setParent(item)
            item.setParent(parent)
            item.setParentItem(parent)
            local_input.bind(item)
            handle = uuid.uuid4().hex
            self.views[handle] = (item, chat)
            def destroyed():
                chat.closed.set()
                local_input.close()
                self.views.pop(handle, None)
            item.destroyed.connect(destroyed)
            return dict(handle=handle, item=item)
        return self.gui.run(mount)

    def release(self, handle):
        def dispose():
            resource = self.views.pop(handle, None)
            if resource:
                item, chat = resource
                chat.closed.set()
                chat.local_input.close()
                if isValid(item):
                    item.setVisible(False)
                    item.setParentItem(None)
                    item.deleteLater()
            return {'released': bool(resource)}
        return self.gui.run(dispose)

    def close(self):
        self.gui.run(lambda: [self.release(handle) for handle in tuple(self.views)])

    def configuration_changed(self):
        self.gui.run(lambda: [chat.configurationChanged.emit() for _, chat in tuple(self.views.values())])
