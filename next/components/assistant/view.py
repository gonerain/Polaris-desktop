"""Local chat view. Model calls run off the GUI thread with the view's original context."""
from pathlib import Path
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Slot, QUrl, Qt
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlContext, qmlEngine
from shiboken6 import isValid
from polaris_platform.protocol import PlatformError
from polaris_platform.desktop.qt_ports import GuiDispatcher


class Chat(QObject):
    answered = Signal(str, str)

    def __init__(self, component, ctx, parent):
        super().__init__(parent)
        self.component, self.ctx = component, ctx
        self.identity = component.port.id
        self.conversation = uuid.uuid4().hex
        self.closed = threading.Event()

    @Slot(str, bool)
    def submit(self, text, enable_tools=False):
        def work():
            try:
                result = self.ctx.call(self.identity, 'reply', dict(text=text, conversation=self.conversation, use_authorized_tools=enable_tools))
                reply, error = result['text'], ''
            except Exception as exc:
                reply, error = '', str(exc)
            if not self.closed.is_set() and isValid(self):
                self.answered.emit(reply, error)
        threading.Thread(target=work, daemon=True, name='polaris-agent-chat').start()


class Presentation:
    def __init__(self, component):
        self.component = component
        self.gui = GuiDispatcher()
        self.views = {}

    def create(self, parent, ctx):
        owner = self.component.port
        def mount():
            if not owner or self.component.port is not owner:
                raise PlatformError('stale_instance', 'Polaris Agent 已停止')
            engine = qmlEngine(parent)
            if not engine:
                raise PlatformError('view_error', '没有 QML 引擎')
            scope = QQmlContext(qmlContext(parent), parent)
            chat = Chat(self.component, ctx, scope)
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
            handle = uuid.uuid4().hex
            self.views[handle] = (item, chat)
            def destroyed():
                chat.closed.set()
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
                if isValid(item):
                    item.setVisible(False)
                    item.setParentItem(None)
                    item.deleteLater()
            return {'released': bool(resource)}
        return self.gui.run(dispose)

    def close(self):
        self.gui.run(lambda: [self.release(handle) for handle in tuple(self.views)])
