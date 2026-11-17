"""Native view bridge. Every read and write crosses ordinary component authority."""
import json
import base64
import shutil
from pathlib import Path
import threading
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlContext, qmlEngine
from shiboken6 import isValid
from polaris_platform.protocol import PlatformError
from polaris_platform.desktop.qt_ports import GuiDispatcher
from .transport import WorkerTransport


class BotBridge(QObject):
    changed = Signal()
    messageSent = Signal()
    attachmentSent = Signal()
    completed = Signal(object)

    def __init__(self, component, ctx, local_input, parent=None):
        super().__init__(parent)
        self.component, self.ctx, self.local_input = component, ctx, local_input
        self.identity = component.port.id
        self.owner_id = uuid4().hex
        self.closed = threading.Event()
        self._polling = False
        self._busy = False
        self._cursor = 0
        self._messages = []
        self._readable = False
        self._chat_app_id = ''
        self._state = dict(instanceName='飞书机器人', appId='', hasSecret=False, configured=False,
            connectionState='disconnected', connectionLabel='未连接', lastError='', notice='',
            busy=False, readable=False, attachment=None, streamId='', chatUrl='', chatQrImageSource='', chatQrModules=0, conversations=[], messages=[], selectedChatId='',
            registration=dict(state='idle', verificationUrl='', qrImageSource='', message='', expiresAt=0))
        self.component.register_registration_owner(self.owner_id, self._validate_registration_owner)
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
                if 'chatEntry' in value:
                    self._state.update(value['chatEntry'])
                    self._chat_app_id = status['appId'] if status['configured'] else ''
                self._state['registration'] = value['registration']
                if backend_error:
                    self._state['lastError'] = backend_error
                self._readable = True
                self._state['readable'] = True
                self._cursor = value['cursor']
                by_id = {message['messageId']: message for message in self._messages + value['messages']}
                self._messages = list(by_id.values())[-1000:]
                messages = [self._display_message(message) for message in self._messages]
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
                if value.get('attachment'):
                    self._state['attachment'] = value['attachment']
                if 'streamId' in value:
                    self._state['streamId'] = value['streamId']
                if value.get('send'):
                    self._state['attachment'] = None
                    if value.get('clearDraft', True):
                        self.messageSent.emit()
                    else:
                        self.attachmentSent.emit()
            self.refresh()
        if value.get('error'):
            self._state['lastError'] = value['error']
            if value['kind'] == 'refresh':
                self._messages = []
                self._cursor = 0
                self._readable = False
                self._state.update(messages=[], conversations=[], selectedChatId='', readable=False,
                    registration=dict(state='idle', verificationUrl='', qrImageSource='', message='', expiresAt=0))
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
                registration = self._registration_snapshot()
                value = dict(kind='refresh', status=status, messages=messages, cursor=cursor, registration=registration)
                app_id = status['appId'] if status['configured'] else ''
                if app_id != self._chat_app_id:
                    if app_id:
                        with self.component._lock:
                            qr_worker = self.component._transport
                        temporary_worker = qr_worker is None
                        if temporary_worker:
                            qr_worker = WorkerTransport(lambda *_: None)
                        try:
                            value['chatEntry'] = qr_worker.request('chat_entry', {'appId': app_id})
                        finally:
                            if temporary_worker:
                                qr_worker.close()
                    else:
                        value['chatEntry'] = dict(chatUrl='', chatQrImageSource='', chatQrModules=0)
            except Exception as error:
                self.component.cancel_registration_owner(self.owner_id)
                value = dict(kind='refresh', error=self._error(error))
            if not self.closed.is_set() and isValid(self):
                self.completed.emit(value)
        threading.Thread(target=work, daemon=True).start()

    def _validate_registration_owner(self):
        if self.closed.is_set():
            raise PlatformError('stale_view', '扫码视图已经关闭')
        self.ctx.call(self.identity, 'status', {})
        self.ctx.call(self.identity, 'read_messages', {'limit': 1})

    def _registration_snapshot(self):
        from .registration import is_registration_url
        raw = self.component.registration_snapshot(self.owner_id)
        state = raw.get('state', 'idle')
        value = dict(state=state, verificationUrl='', qrImageSource='', message=raw.get('message', ''),
                     expiresAt=raw.get('expiresAt', 0))
        url = raw.get('verificationUrl', '')
        if state in ('waiting', 'scanned', 'creating', 'expired', 'error') and url and is_registration_url(url):
            value['verificationUrl'] = url
            source = raw.get('qrDataUrl', '')
            if (isinstance(source, str) and source.startswith('data:image/svg+xml;base64,')
                    and len(source) <= 2_000_000):
                value['qrImageSource'] = source
                modules = raw.get('qrModules', 0)
                if type(modules) is int and 21 <= modules <= 185:
                    value['qrModules'] = modules
        return value

    @Slot()
    def openChat(self):
        if not self.closed.is_set() and self._state['configured']:
            QDesktopServices.openUrl(QUrl(self._state['chatUrl']))

    @Slot()
    def startRegistration(self):
        if self.closed.is_set():
            return
        self.component.register_registration_owner(self.owner_id, self._validate_registration_owner)
        self._action('start_registration', dict(name=self._state['instanceName'], owner_id=self.owner_id))

    @Slot()
    def cancelRegistration(self):
        self._action('cancel_registration', dict(owner_id=self.owner_id))

    @Slot()
    def openRegistrationLink(self):
        from .registration import is_registration_url
        url = self._state['registration'].get('verificationUrl', '')
        if not self.closed.is_set() and is_registration_url(url):
            QDesktopServices.openUrl(QUrl(url))

    def _action(self, operation, params, completion=None):
        if self.closed.is_set() or self._busy:
            return
        if operation in ('send', 'upload_media', 'download_resource', 'start_stream', 'update_stream', 'finish_stream') and not self._readable:
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
                result = self.component.execute_prepared(ticket)
                if completion:
                    value.update(completion(result))
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

    @staticmethod
    def _display_message(message):
        value = dict(message)
        normalized = message.get('normalized') or {}
        sender = normalized.get('sender') or {}
        if isinstance(sender, dict):
            value['senderLabel'] = sender.get('display_name') or value.get('sender') or sender.get('open_id') or '收到消息'
        else:
            value['senderLabel'] = value.get('sender') or '收到消息'
        return value

    @Slot(str)
    def resumeStream(self, stream_id):
        self._state['streamId'] = stream_id
        self.changed.emit()

    @Slot(str)
    def chooseAttachment(self, url):
        path = Path(QUrl(url).toLocalFile())
        try:
            data = base64.b64encode(path.read_bytes()).decode('ascii')
        except OSError as error:
            self._state['lastError'] = str(error)
            self.changed.emit()
            return
        kind = 'image' if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp') else 'file'
        self._action('upload_media', dict(data_base64=data, file_name=path.name, kind=kind),
            lambda result: dict(attachment=dict(result, name=path.name, kind=kind)))

    @Slot()
    def clearAttachment(self):
        self._state['attachment'] = None
        self.changed.emit()

    @Slot(str, str, str, str, bool)
    def sendDraft(self, target_type, target_id, text, reply_id, in_thread):
        params = dict(target_type=target_type, target_id=target_id,
            reply_message_id=reply_id or None, reply_in_thread=in_thread if reply_id else None)
        attachment = self._state['attachment']
        if attachment:
            params['message'] = self._attachment_message(attachment, text)
        else:
            params['text'] = text
        self._action('send', params, lambda result: dict(clearDraft=not attachment or attachment['kind'] == 'image'))

    @staticmethod
    def _attachment_message(attachment, text):
        media = dict(source=attachment['media_key'])
        if attachment['kind'] == 'file':
            media['file_name'] = attachment['name']
        return {attachment['kind']: media, **({'caption': text} if text and attachment['kind'] == 'image' else {})}

    @Slot(str, str, str, str, str)
    def saveResource(self, file_key, message_id, resource_type, file_name, destination):
        path = QUrl(destination).toLocalFile()
        def save(result):
            shutil.copyfile(result['path'], path)
            return {}
        self._action('download_resource', dict(file_key=file_key, message_id=message_id or None,
            resource_type=resource_type, file_name=file_name or None), save)

    @Slot(str, str, str, str, bool)
    def startStream(self, target_type, target_id, text, reply_id, in_thread):
        self._action('start_stream', dict(target_type=target_type, target_id=target_id, text=text,
            reply_message_id=reply_id or None, reply_in_thread=in_thread if reply_id else None),
            lambda result: dict(streamId=result['stream_id']))

    @Slot(str)
    def updateStream(self, text):
        self._action('update_stream', dict(stream_id=self._state['streamId'], text=text))

    @Slot(str)
    def finishStream(self, text):
        self._action('finish_stream', dict(stream_id=self._state['streamId'], text=text),
            lambda result: dict(streamId='', send=True))

    def close(self):
        self.closed.set()
        self.timer.stop()
        self.component.cancel_registration_owner(self.owner_id)
        self._state['registration'] = dict(state='cancelled', verificationUrl='', qrImageSource='', message='', expiresAt=0)
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
