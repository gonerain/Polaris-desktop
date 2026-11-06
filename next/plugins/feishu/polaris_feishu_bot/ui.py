"""Native view bridge. Every read and write crosses ordinary component authority."""
import json
from pathlib import Path
import threading
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl, QTimer
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlContext, qmlEngine
from shiboken6 import isValid
from polaris_platform.protocol import PlatformError
from polaris_platform.desktop.qt_ports import GuiDispatcher


class BotBridge(QObject):
    changed = Signal()
    messageSent = Signal()
    completed = Signal(object)

    def __init__(self, component, ctx, local_input, parent=None):
        super().__init__(parent)
        self.component, self.ctx, self.local_input = component, ctx, local_input
        self.identity = component.port.id
        self.closed = threading.Event()
        self._polling = False
        self._busy = False
        self._cursor = 0
        self._messages = []
        self._readable = False
        self._state = dict(instanceName='飞书机器人', appId='', hasSecret=False, configured=False,
            connectionState='disconnected', connectionLabel='未连接', lastError='', notice='',
            busy=False, readable=False, conversations=[], messages=[], selectedChatId='')
        self.completed.connect(self._complete)
        self.timer = QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    @Property(str, notify=changed)
    def stateJson(self):
        return json.dumps(self._state, ensure_ascii=False)

    @Slot(object)
    def _complete(self, value):
        if self.closed.is_set():
            return
        if value['kind'] == 'refresh':
            self._polling = False
            if 'status' in value:
                status = dict(value['status'])
                backend_error = status.pop('lastError', '')
                self._state.update(status)
                if backend_error:
                    self._state['lastError'] = backend_error
                self._readable = True
                self._state['readable'] = True
                self._cursor = value['cursor']
                self._messages = (self._messages + value['messages'])[-1000:]
                messages = self._messages
                conversations = {}
                for message in messages:
                    conversations[message['chatId']] = dict(chatId=message['chatId'], title=message['chatId'], lastText=message.get('text', ''))
                self._state['conversations'] = list(conversations.values())
                selected = self._state['selectedChatId']
                if not selected and conversations:
                    selected = next(reversed(conversations))
                    self._state['selectedChatId'] = selected
                self._state['messages'] = [message for message in messages if message['chatId'] == selected]
        else:
            self._busy = False
            self._state['busy'] = False
            if not value.get('error'):
                self._state['notice'] = '操作完成'
                self._state['lastError'] = ''
                if value.get('send'):
                    self.messageSent.emit()
            self.refresh()
        if value.get('error'):
            self._state['lastError'] = value['error']
            if value['kind'] == 'refresh':
                self._messages = []
                self._cursor = 0
                self._readable = False
                self._state.update(messages=[], conversations=[], selectedChatId='', readable=False)
        self._state['connectionLabel'] = {'disconnected': '未连接', 'connecting': '连接中',
            'connected': '已连接', 'error': '连接异常'}.get(self._state['connectionState'], '未连接')
        self.changed.emit()

    @staticmethod
    def _error(error):
        return error.message if isinstance(error, PlatformError) else '飞书操作未能完成，请重试'

    @Slot()
    def refresh(self):
        if self.closed.is_set() or self._polling:
            return
        self._polling = True
        def work():
            try:
                status = self.ctx.call(self.identity, 'status', {})
                cursor = self._cursor
                messages = []
                for _ in range(20):
                    result = self.ctx.call(self.identity, 'read_messages', {'after': cursor, 'limit': 500})
                    messages.extend(result['items'])
                    cursor = result['nextCursor']
                    if len(result['items']) < 500:
                        break
                value = dict(kind='refresh', status=status, messages=messages, cursor=cursor)
            except Exception as error:
                value = dict(kind='refresh', error=self._error(error))
            if not self.closed.is_set() and isValid(self):
                self.completed.emit(value)
        threading.Thread(target=work, daemon=True).start()

    def _action(self, operation, params):
        if self.closed.is_set() or self._busy:
            return
        if operation == 'send' and not self._readable:
            self._state['lastError'] = '当前视图授权已失效，请重新打开后再发送'
            self.changed.emit()
            return
        try:
            ticket = self.component.authorize_from_view(self.local_input, operation, params)
        except Exception as error:
            self._state['lastError'] = self._error(error)
            self.changed.emit()
            return
        self._busy = True
        self._state.update(busy=True, lastError='', notice='')
        self.changed.emit()
        def work():
            value = dict(kind='action', send=operation == 'send')
            try:
                self.component.execute_prepared(ticket)
            except Exception as error:
                value['error'] = self._error(error)
            if not self.closed.is_set() and isValid(self):
                self.completed.emit(value)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str, str)
    def saveConfiguration(self, name, app_id, secret):
        self._action('configure', dict(name=name, app_id=app_id, secret=secret))

    @Slot()
    def connectBot(self):
        self._action('connect', {})

    @Slot()
    def disconnectBot(self):
        self._action('disconnect', {})

    @Slot(str)
    def selectConversation(self, chat_id):
        self._state['selectedChatId'] = chat_id
        self.refresh()

    @Slot(str, str, str)
    def sendMessage(self, chat_id, text, reply_message_id):
        self._action('send', dict(chat_id=chat_id, text=text, reply_message_id=reply_message_id or None))

    def close(self):
        self.closed.set()
        self.timer.stop()
        self.local_input.close()


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
                raise PlatformError('stale_instance', '飞书机器人实例已停止')
            engine = qmlEngine(parent)
            if not engine:
                raise PlatformError('view_error', '缺少 QML 引擎')
            scope = QQmlContext(qmlContext(parent), parent)
            bridge = BotBridge(self.component, ctx, local_input, scope)
            scope.setContextProperty('feishuBot', bridge)
            definition = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Feishu.qml'))))
            item = definition.create(scope)
            if item is None:
                bridge.close()
                scope.deleteLater()
                definition.deleteLater()
                raise PlatformError('view_error', '; '.join(error.toString() for error in definition.errors()))
            scope.setParent(item)
            definition.setParent(item)
            item.setParent(parent)
            item.setParentItem(parent)
            local_input.bind(item)
            handle = uuid4().hex
            self.views[handle] = (item, bridge)
            item.destroyed.connect(lambda: (bridge.close(), self.views.pop(handle, None)))
            return {'handle': handle, 'item': item}
        return self.gui.run(mount)

    def release(self, handle):
        def dispose():
            resource = self.views.pop(handle, None)
            if resource:
                item, bridge = resource
                bridge.close()
                if isValid(item):
                    item.setVisible(False)
                    item.setParentItem(None)
                    item.deleteLater()
            return {'released': bool(resource)}
        return self.gui.run(dispose)

    def close(self):
        self.gui.run(lambda: [self.release(handle) for handle in tuple(self.views)])
