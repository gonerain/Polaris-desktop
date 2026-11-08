"""Native, instance-scoped Feishu bot component."""
from copy import deepcopy
from pathlib import Path
import threading
import time
from uuid import uuid4
from polaris_platform.protocol import PlatformError
from polaris_platform.sdk import Component
from .store import Store
from .transport import WorkerTransport
from .registration import RegistrationController
from .message_backend import MessageBackend


class FeishuBot(MessageBackend, Component):
    def __init__(self, instance_context, transport_factory=None, registration_transport_factory=None):
        super().__init__()
        self.instance_id = instance_context['instanceId']
        self.store = Store(instance_context['dataDir'])
        self._transport_factory = transport_factory or WorkerTransport
        self._transport = None
        self._lock = threading.RLock()
        self._network_lock = threading.RLock()
        self._stopped = True
        self._generation = 0
        self._state = 'disconnected'
        self._error = ''
        self._actions = {}
        self._human_contexts = set()
        self._view_action = threading.local()
        self.presentation = None
        self.registration = RegistrationController(self, registration_transport_factory or WorkerTransport)
        self.views = [dict(id='main', title='飞书机器人', adapter='qt-quick-item',
            create='create_view', release='release_view', preferredSize=dict(width=760, height=600),
            permissions=[dict(name=name, access='read') for name in ('status', 'read_messages')])]
        for name, handler in [('status', self.status), ('read_messages', self.read_messages),
                              ('read_card_actions', self.read_card_actions), ('read_attachment', self.read_attachment)]:
            self.operation(name, provides='polaris.feishu.' + name.replace('_', '-') + '@1',
                           applicationBinding='instance')(handler)
        for name, handler in [('send', self.send), ('reply', self.reply), ('send_card', self.send_card),
                              ('update_card', self.update_card), ('upload_media', self.upload_media),
                              ('download_resource', self.download_resource), ('start_stream', self.start_stream),
                              ('update_stream', self.update_stream), ('finish_stream', self.finish_stream)]:
            self.operation(name, access='write', provides='polaris.feishu.' + name.replace('_', '-') + '@1',
                           applicationBinding='instance')(handler)
        for name, handler in [('configure', self.configure), ('connect', self.connect),
                              ('disconnect', self.disconnect), ('prepare_action', self.prepare_action),
                              ('start_registration', self.start_registration), ('cancel_registration', self.cancel_registration),
                              ('registration_checkpoint', self.registration_checkpoint),
                              ('create_view', self.create_view), ('release_view', self.release_view)]:
            self.operation(name, access='write')(handler)

    def describe(self):
        value = super().describe()
        from .api_help import public_help
        for name, help in public_help().items():
            value['operations'][name].update(help)
        for name in ('configure', 'connect', 'disconnect', 'prepare_action', 'start_registration', 'cancel_registration', 'registration_checkpoint'):
            value['operations'][name].update(humanOnly=True, modelCallable=False)
        for name in ('create_view', 'release_view'):
            value['operations'][name]['profile'] = 'qt-native'
        return value

    def start(self, port):
        super().start(port)
        with self._lock:
            self._stopped = False
            self._generation += 1
            generation = self._generation
        if self.store.configuration().get('desiredConnected', False):
            def resume():
                try:
                    with self._lock:
                        if self._stopped or generation != self._generation:
                            return
                    self._connect(expected_generation=generation)
                except PlatformError:
                    pass
            threading.Thread(target=resume, daemon=True, name='feishu-resume').start()

    def stop(self):
        self.registration.cancel()
        self.registration.owners.clear()
        with self._lock:
            self._stopped = True
            self._generation += 1
            self._actions.clear()
            self._human_contexts.clear()
            transport, self._transport = self._transport, None
            presentation, self.presentation = self.presentation, None
            self._state = 'disconnected'
        if presentation:
            presentation.close()
        if transport:
            transport.close()
        super().stop()

    def _check(self):
        if self._stopped:
            raise PlatformError('stale_instance', '飞书机器人实例已停止')

    def status(self):
        with self._lock:
            self._check()
            config = self.store.configuration()
            return dict(instanceId=self.instance_id, instanceName=config['instanceName'],
                appId=config['appId'], hasSecret=bool(config['secret']),
                configured=bool(config['appId'] and config['secret']),
                connectionState=self._state, lastError=self._error, sdkVersion='1.4.0',
                activeStreams=self.store.active_streams())

    @staticmethod
    def _text(value, label, maximum=20000):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise PlatformError('invalid_params', label + '不能为空或超过长度限制')
        return value.strip()

    def _human(self, ctx):
        self._check()
        context = ctx.context
        if (context.request_id not in self._human_contexts or context.source != 'user'
                or context.origin != self.port.id or context.caller != self.port.id):
            raise PlatformError('permission_denied', '此设置只能从当前飞书机器人本机界面操作')

    def configure(self, name, app_id, secret='', ctx=None):
        self._human(ctx)
        name = self._text(name, '实例名称', 100)
        app_id = self._text(app_id, 'App ID', 200)
        if not isinstance(secret, str) or len(secret) > 2048:
            raise PlatformError('invalid_params', 'App Secret 格式无效')
        self.registration.cancel()
        with self._network_lock:
            previous = self.store.configuration()
            if previous['appId'] and previous['appId'] != app_id:
                raise PlatformError('new_instance_required', '更换机器人 App ID 请新建飞书机器人实例')
            if self._state in ('connecting', 'connected'):
                raise PlatformError('disconnect_required', '请先断开连接再修改配置')
            if not secret:
                secret = previous['secret']
            if not secret:
                raise PlatformError('invalid_params', '首次配置需要 App Secret')
            self.store.configure(dict(instanceName=name, appId=app_id, secret=secret,
                                      desiredConnected=previous.get('desiredConnected', False)))
        return self.status()

    def _receive(self, generation, event, payload):
        with self._lock:
            if self._stopped or generation != self._generation:
                return
            if event in ('message', 'card_action'):
                self.store.append('message' if event == 'message' else 'card_action', payload)
            elif event == 'connection':
                self._state = payload.get('connectionState', self._state)
                self._error = payload.get('lastError', '')

    def connect(self, ctx):
        self._human(ctx)
        config = self.store.configuration()
        config['desiredConnected'] = True
        self.store.configure(config)
        return self._connect()

    def _connect(self, expected_generation=None):
        with self._network_lock:
            with self._lock:
                self._check()
                if expected_generation is not None and expected_generation != self._generation:
                    return self.status()
            config = self.store.configuration()
            if not config['appId'] or not config['secret']:
                raise PlatformError('not_configured', '请先配置 App ID 和 App Secret')
            with self._lock:
                self._check()
                if self._state == 'connected':
                    return self.status()
                previous = self._transport
                self._generation += 1
                generation = self._generation
                transport = self._transport_factory(lambda event, payload: self._receive(generation, event, payload))
                self._transport = transport
                self._state, self._error = 'connecting', ''
            if previous:
                previous.close()
            try:
                result = transport.request('connect', {'appId': config['appId'], 'secret': config['secret']})
                with self._lock:
                    self._check()
                    if generation != self._generation:
                        raise PlatformError('stale_instance', '连接操作已取消')
                    self._state = result['connectionState']
            except Exception as error:
                transport.close()
                message = error.message if isinstance(error, PlatformError) else '飞书连接失败，请检查应用凭据、权限和网络'
                with self._lock:
                    if generation == self._generation:
                        self._state, self._error = 'error', message
                if isinstance(error, PlatformError):
                    raise
                raise PlatformError('feishu_connect_failed', message) from None
        return self.status()

    def disconnect(self, ctx):
        self._human(ctx)
        self.registration.cancel()
        config = self.store.configuration()
        config['desiredConnected'] = False
        self.store.configure(config)
        with self._lock:
            self._generation += 1
            transport, self._transport = self._transport, None
            self._state, self._error = 'disconnected', ''
        if transport:
            transport.close()
        return self.status()

    def _read(self, kind, after, limit, chat_id):
        self._check()
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise PlatformError('invalid_params', '游标或数量无效')
        if chat_id is not None and not isinstance(chat_id, str):
            raise PlatformError('invalid_params', '会话标识无效')
        return self.store.read(kind, after, limit, chat_id)

    def read_messages(self, after=0, limit=100, chat_id=None):
        return self._read('message', after, limit, chat_id)

    def read_card_actions(self, after=0, limit=100, chat_id=None):
        return self._read('card_action', after, limit, chat_id)

    def _send(self, operation, params, text=''):
        with self._network_lock:
            self._check()
            with self._lock:
                transport, generation = self._transport, self._generation
                if transport is None or self._state != 'connected':
                    raise PlatformError('not_connected', '请先连接飞书机器人')
            params = dict(params, requestId=uuid4().hex)
            try:
                result = transport.request(operation, params)
            except PlatformError as error:
                if error.code in ('feishu_timeout', 'feishu_disconnected'):
                    with self._lock:
                        if generation == self._generation:
                            self._state, self._error = 'error', error.message
                raise
            with self._lock:
                self._check()
                if generation != self._generation:
                    raise PlatformError('stale_instance', '发送操作所属连接已关闭')
                if operation != 'update_card':
                    self.store.append('message', dict(messageId=result['messageId'], chatId=params['chatId'],
                        sender='机器人', text=text, direction='outbound', messageType='card' if operation == 'send_card' else 'text',
                        replyMessageId=params.get('replyMessageId', '')))
            return result

    @staticmethod
    def _card(card):
        import json
        try:
            valid = isinstance(card, dict) and len(json.dumps(card, allow_nan=False)) <= 50000
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise PlatformError('invalid_params', '卡片须为不超过 50000 字符的 JSON 对象')
        return deepcopy(card)

    def send_card(self, chat_id, card):
        return self._send('send_card', dict(chatId=self._text(chat_id, '会话标识', 200), card=self._card(card)), '[卡片]')

    def update_card(self, message_id, card):
        message_id = self._text(message_id, '消息标识', 200)
        known = self.store.message(message_id)
        if known is None or known['direction'] != 'outbound' or known.get('messageType') not in ('card', 'interactive'):
            raise PlatformError('message_missing', '只能更新当前实例已发送的卡片消息')
        return self._send('update_card', dict(messageId=message_id, card=self._card(card)))

    def authorize_from_view(self, local_input, operation, params):
        self._view_action.active = True
        try:
            return local_input.call('prepare_action', dict(operation=operation, params=params),
                permissions=[(self.port.id, 'prepare_action'), (self.port.id, operation)]
                    + ([(self.port.id, 'registration_checkpoint')] if operation == 'start_registration' else []))['ticket']
        finally:
            self._view_action.active = False

    def prepare_action(self, operation, params, ctx):
        self._check()
        if not getattr(self._view_action, 'active', False) or operation not in ('configure', 'connect', 'disconnect', 'send', 'upload_media', 'download_resource',
                'start_stream', 'update_stream', 'finish_stream', 'start_registration', 'cancel_registration'):
            raise PlatformError('permission_denied', '操作必须来自当前本机界面')
        ticket = uuid4().hex
        with self._lock:
            self._actions = {key: value for key, value in self._actions.items() if value[3] > time.monotonic()}
            self._actions[ticket] = (operation, deepcopy(params), ctx.context, time.monotonic() + 30)
        return {'ticket': ticket}

    def execute_prepared(self, ticket):
        with self._lock:
            action = self._actions.pop(ticket, None)
            if action is None or action[3] < time.monotonic():
                raise PlatformError('stale_action', '本机操作已失效，请重试')
            operation, params, context, _ = action
            port = self.port
            self._human_contexts.add(context.request_id)
        try:
            return port.call(port.id, operation, params, context=context)
        finally:
            with self._lock:
                self._human_contexts.discard(context.request_id)

    def start_registration(self, name, owner_id, ctx):
        self._human(ctx)
        name = self._text(name, '机器人名称', 100)
        owner_id = self._text(owner_id, '本机视图标识', 128)
        if owner_id not in self.registration.owners:
            raise PlatformError('stale_view', '本机视图已关闭，请重新打开')
        return self.registration.start(name, owner_id, ctx.context)

    def cancel_registration(self, owner_id, ctx):
        self._human(ctx)
        return self.registration.cancel(owner_id)

    def registration_checkpoint(self, session_id, ctx):
        return self.registration.checkpoint(session_id, ctx)

    def register_registration_owner(self, owner_id, validator):
        with self._lock:
            self._check()
            self.registration.owners[owner_id] = validator

    def registration_snapshot(self, owner_id):
        return self.registration.snapshot(owner_id)

    def cancel_registration_owner(self, owner_id):
        with self._lock:
            self.registration.owners.pop(owner_id, None)
        self.registration.cancel(owner_id)

    def create_view(self, view, parent, ctx):
        self._check()
        if view != 'main':
            raise PlatformError('missing_view', view)
        if self.presentation is None:
            from .ui import Presentation
            self.presentation = Presentation(self)
        return self.presentation.create(parent, ctx)

    def release_view(self, handle):
        return self.presentation.release(handle) if self.presentation else {'released': False}


def create(instance_context):
    return FeishuBot(instance_context)
