"""Official application registration, isolated from application-readable status."""
import asyncio
import base64
import io
from copy import deepcopy
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
from polaris_platform.protocol import PlatformError

ADDONS = {
    'preset': False,
    'scopes': {'tenant': ['im:message:send_as_bot', 'im:message.p2p_msg:readonly',
                          'im:message.group_at_msg:readonly', 'im:message:update',
                          'im:resource', 'cardkit:card:write']},
    'events': {'items': {'tenant': ['im.message.receive_v1']}},
    'callbacks': {'items': ['card.action.trigger']},
}



def is_registration_url(value):
    if not isinstance(value, str) or len(value) > 20000:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and parsed.hostname in ('open.feishu.cn', 'accounts.feishu.cn')
                and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                and not any(character.isspace() or ord(character) < 32 for character in value))
    except ValueError:
        return False


def qr_image(value):
    if not is_registration_url(value):
        raise RegistrationError('invalid_response')
    import qrcode
    from qrcode.image.svg import SvgPathImage
    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(value)
    qr.make(fit=True)
    output = io.BytesIO()
    qr.make_image(image_factory=SvgPathImage).save(output)
    data = 'data:image/svg+xml;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    return data, qr.modules_count + 8


def qr_data_url(value):
    return qr_image(value)[0]


class RegistrationNetworkError(Exception):
    pass


class RegistrationError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def failure_state(error):
    code = getattr(error, 'code', '')
    if code == 'expired_token':
        return 'expired', '飞书提示此二维码已过期，点击刷新二维码即可'
    if code == 'access_denied':
        return 'error', '飞书确认已拒绝，可重新开始'
    if code == 'unsupported_brand':
        return 'error', '此组件仅支持飞书租户，请使用飞书账号重新扫码'
    if code == 'invalid_response':
        return 'error', '飞书返回的注册信息无效，请重新开始'
    if code == 'credential_verification_failed':
        return 'error', '应用未通过飞书认证校验，请检查确认结果后重试'
    return 'error', '扫码接入未能完成，请检查网络后重试'


async def verify_feishu_credentials(app_id, secret):
    """Verify against a fixed Feishu authority; discard the returned tenant token."""
    import httpx
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        response = await client.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                                     json={'app_id': app_id, 'app_secret': secret})
        if response.status_code in (408, 429, 500, 502, 503, 504):
            raise RegistrationNetworkError()
        if response.status_code != 200:
            raise RegistrationError('credential_verification_failed')
        data = response.json()
        if (not isinstance(data, dict) or type(data.get('code')) is not int or data['code'] != 0
                or not isinstance(data.get('tenant_access_token'), str) or not data['tenant_access_token']):
            raise RegistrationError('credential_verification_failed')
        # The token is never emitted, persisted, or logged.


async def register_until_confirmed(**options):
    """Use SDK request/response handling, but only the server expires a device code."""
    import httpx
    from lark_oapi.scene.registration import _AsyncFlow
    class UserControlledFlow(_AsyncFlow):
        async def _post(self, data):
            from urllib.parse import urlencode
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(self._base_url + '/oauth/v1/app/registration',
                    content=urlencode(data), headers={'Content-Type': 'application/x-www-form-urlencoded'})
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    raise RegistrationNetworkError()
                payload = response.json()
                # OAuth errors may use HTTP 400/403; preserve the SDK's semantic handling.
                if isinstance(payload, dict) and isinstance(payload.get('error'), str) and payload['error']:
                    return payload
                response.raise_for_status()
                return payload

        async def _initial_request(self, data):
            while True:
                try:
                    return await self._post(data)
                except (httpx.TransportError, asyncio.TimeoutError, RegistrationNetworkError):
                    self._notify_status('initial_network_retry')
                    await asyncio.sleep(3)

        async def run(self):
            init = await self._initial_request({'action': 'init'})
            if 'client_secret' not in (init.get('supported_auth_methods') or []):
                raise RegistrationError('unsupported_auth_method')
            begin = await self._initial_request(dict(action='begin', archetype='PersonalAgent',
                auth_method='client_secret', request_user_info='open_id'))
            device = begin['device_code']
            self._on_qr_code(dict(url=self._build_qr_url(begin['verification_uri_complete']),
                                 expire_in=begin.get('expires_in')))
            interval = begin.get('interval', 5)
            interval = max(1, interval) if type(interval) in (int, float) and 0 <= interval <= 300 else 5
            while True:
                try:
                    response = await self._post({'action': 'poll', 'device_code': device})
                except (httpx.TransportError, asyncio.TimeoutError, RegistrationNetworkError):
                    self._notify_status('network_retry')
                    await asyncio.sleep(max(interval, 1))
                    continue
                action, result = self._handle_poll_response(response, False)
                if action == 'success':
                    return result
                if action == 'slow_down':
                    interval = min(interval + 5, 300)
                    self._notify_status('slow_down', interval)
                await asyncio.sleep(interval)
    return await UserControlledFlow(domain='https://accounts.feishu.cn',
        lark_domain='https://accounts.larksuite.com', **options).run()


async def run_registration(emit, name, register=None, verify=None):
    """Wait until user cancellation or an explicit server result."""
    if register is None:
        register = register_until_confirmed
    verify = verify or verify_feishu_credentials
    switched = False
    def qr(info):
        if not isinstance(info, dict) or not is_registration_url(info.get('url')):
            raise RegistrationError('invalid_response')
        lifetime = info.get('expire_in')
        image, modules = qr_image(info['url'])
        emit({'state': 'waiting', 'verificationUrl': info['url'], 'qrDataUrl': image, 'qrModules': modules,
              'expiresAt': time.time() + lifetime if type(lifetime) in (int, float) and lifetime > 0 else 0,
              'message': '请用飞书扫码，并在官方确认页核对机器人权限及消息、卡片的长连接配置'})
    def status(info):
        nonlocal switched
        if not isinstance(info, dict):
            raise RegistrationError('invalid_response')
        state = info.get('status')
        if state == 'domain_switched':
            switched = True
            raise RegistrationError('unsupported_brand')
        if state == 'initial_network_retry':
            emit({'state': 'creating', 'message': '正在申请二维码，网络暂时未响应；将继续重试，可随时取消'})
        if state == 'network_retry':
            emit({'state': 'waiting', 'message': '网络暂时未响应，正在继续等待飞书确认；可手动刷新二维码'})
        if state in ('polling', 'slow_down'):
            emit({'state': 'waiting', 'message': '等待飞书确认' if state == 'polling' else '飞书要求放慢查询，正在等待确认'})
    async def perform():
        result = await register(on_qr_code=qr, on_status_change=status,
            source='polaris-feishu-bot', app_preset={'name': name, 'desc': '北极星飞书机器人'},
            addons=deepcopy(ADDONS), create_only=True)
        if not isinstance(result, dict):
            raise RegistrationError('invalid_response')
        info = result.get('user_info') or {}
        if not isinstance(info, dict):
            raise RegistrationError('invalid_response')
        if switched or info.get('tenant_brand') not in (None, '', 'feishu'):
            raise RegistrationError('unsupported_brand')
        app_id, secret = result.get('client_id'), result.get('client_secret')
        if (not isinstance(app_id, str) or not re.fullmatch(r'cli_[A-Za-z0-9_-]{1,196}', app_id)
                or not isinstance(secret, str) or not secret.strip() or len(secret) > 2048):
            raise RegistrationError('invalid_response')
        emit({'state': 'creating', 'message': '已确认，正在校验飞书应用凭据'})
        import httpx
        while True:
            try:
                await verify(app_id, secret)
                break
            except (httpx.TransportError, asyncio.TimeoutError, RegistrationNetworkError):
                emit({'state': 'creating', 'message': '正在确认应用凭据，网络暂时未响应；将继续重试'})
                await asyncio.sleep(3)
        emit({'state': 'credentials', 'client_id': app_id, 'client_secret': secret, 'verifiedFeishu': True})
    try:
        await perform()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        state, message = failure_state(error)
        emit({'state': state, 'message': message})


class RegistrationController:
    """One cancellable local view session per stable component instance."""
    def __init__(self, component, transport_factory):
        self.component = component
        self.transport_factory = transport_factory
        self.current = None
        self.owners = {}

    @staticmethod
    def idle():
        return {'state': 'idle', 'verificationUrl': '', 'qrDataUrl': '', 'qrModules': 0, 'expiresAt': 0, 'message': ''}

    def _valid(self, session):
        component = self.component
        with component._lock:
            if (component._stopped or self.current is not session or session['cancelled']
                    or component.port is not session['port']):
                return False
        try:
            validator = self.owners.get(session['owner'])
            if validator is None:
                return False
            validator()
            session['port'].call(session['port'].id, 'registration_checkpoint',
                                 {'session_id': session['id']}, context=session['context'])
            return True
        except Exception:
            return False

    def checkpoint(self, session_id, ctx):
        component = self.component
        with component._lock:
            session = self.current
            if (session is None or session['id'] != session_id or session['cancelled']
                    or component._stopped or component.port is not session['port']
                    or ctx.context.request_id != session['context'].request_id):
                raise PlatformError('stale_registration', '扫码接入会话已失效')
        ctx.require_permissions([(component.port.id, 'start_registration')])
        return {'active': True}

    @staticmethod
    def _retire(transport):
        if transport is not None:
            threading.Thread(target=transport.close, daemon=True, name='feishu-registration-close').start()

    def cancel(self, owner=None, message='扫码接入已取消', expected_session=None, state='cancelled'):
        component = self.component
        with component._lock:
            session = self.current
            if (session is None or owner is not None and session['owner'] != owner
                    or expected_session is not None and session is not expected_session):
                return self.idle()
            if session['snapshot']['state'] == 'connecting' and session.get('committed'):
                config = component.store.configuration()
                config['desiredConnected'] = False
                component.store.configure(config)
                baseline = session.get('connect_baseline')
                if baseline is not None and component._generation in (baseline, baseline + 1):
                    component._generation += 1
                    connection, component._transport = component._transport, None
                    component._state = 'disconnected'
                    self._retire(connection)
            session['cancelled'] = True
            session['snapshot'] = dict(self.idle(), state=state, message=message)
            transport, session['transport'] = session['transport'], None
        self._retire(transport)
        return dict(session['snapshot'])

    def start(self, name, owner, context):
        component = self.component
        with component._lock:
            component._check()
            if component.store.configuration().get('appId'):
                raise PlatformError('already_configured', '当前实例已关联机器人；如需新机器人，请新建实例')
        self.cancel()
        session = dict(id=uuid4().hex, owner=owner, context=context, port=component.port,
            name=name, cancelled=False,
            snapshot=dict(self.idle(), state='creating', message='正在向飞书申请二维码'), transport=None)
        with component._lock:
            self.current = session
        def begin():
            try:
                if not self._valid(session):
                    self.cancel(owner, expected_session=session)
                    return
                transport = self.transport_factory(lambda event, payload: self.event(session, event, payload))
                with component._lock:
                    if self.current is not session or session['cancelled']:
                        self._retire(transport)
                        return
                    session['transport'] = transport
                transport.request('registration_start', {'name': name})
            except Exception:
                self.event(session, 'registration', {'state': 'error', 'message': '无法开始扫码接入，请检查网络后重试'})
        threading.Thread(target=begin, daemon=True, name='feishu-registration-start').start()
        return dict(session['snapshot'])

    def snapshot(self, owner):
        component = self.component
        with component._lock:
            session = self.current
            if session is None or session['owner'] != owner:
                return self.idle()
            active = session['snapshot']['state'] in ('creating', 'waiting', 'connecting') and not session['cancelled']
        if active and not self._valid(session):
            self.cancel(owner, '本机授权已失效，请重新开始', expected_session=session)
        with component._lock:
            return dict(session['snapshot'])

    def event(self, session, event, payload):
        component = self.component
        with component._lock:
            if self.current is not session or session['cancelled'] or session['snapshot']['state'] in ('error', 'expired', 'complete', 'cancelled'):
                return
        if event != 'registration':
            if event == 'connection':
                with component._lock:
                    active = self.current is session and not session['cancelled'] and session['snapshot']['state'] in ('creating', 'waiting')
                if active:
                    self.event(session, 'registration', {'state': 'error', 'message': '扫码连接已结束，请重新开始'})
            return
        if not self._valid(session):
            with component._lock:
                current = self.current is session
            if current:
                self.cancel(session['owner'], '扫码接入已取消或本机授权已失效', expected_session=session)
            return
        state = payload.get('state') if isinstance(payload, dict) else None
        if state == 'credentials':
            self._finish(session, payload)
            return
        if state not in ('creating', 'waiting', 'error', 'expired'):
            state, payload = 'error', {'message': '飞书返回的注册状态无效'}
        with component._lock:
            if self.current is not session or session['cancelled']:
                return
            snapshot = session['snapshot']
            snapshot.update(state=state, message=payload.get('message', ''))
            if 'verificationUrl' in payload:
                url = payload['verificationUrl']
                if url and not is_registration_url(url):
                    snapshot.update(state='error', verificationUrl='', qrDataUrl='', message='飞书返回的确认地址无效')
                else:
                    snapshot['verificationUrl'] = url
            if 'qrDataUrl' in payload:
                image = payload['qrDataUrl']
                if isinstance(image, str) and image.startswith('data:image/svg+xml;base64,') and len(image) < 1000000:
                    snapshot['qrDataUrl'] = image
                else:
                    snapshot.update(state='error', message='二维码生成失败，请重新开始')
            if 'qrModules' in payload:
                modules = payload['qrModules']
                if type(modules) is int and 21 <= modules <= 185:
                    snapshot['qrModules'] = modules
            if type(payload.get('expiresAt')) in (int, float):
                snapshot['expiresAt'] = payload['expiresAt']
            terminal = snapshot['state'] in ('error', 'expired')
            transport = session['transport'] if terminal else None
            if terminal:
                session['transport'] = None
        self._retire(transport)

    def _finish(self, session, payload):
        component = self.component
        app_id, secret = payload.get('client_id'), payload.get('client_secret')
        if (payload.get('verifiedFeishu') is not True or not isinstance(app_id, str)
                or not re.fullmatch(r'cli_[A-Za-z0-9_-]{1,196}', app_id)
                or not isinstance(secret, str) or not secret.strip() or len(secret) > 2048):
            self.event(session, 'registration', {'state': 'error', 'message': '飞书应用校验未完成，请重新开始'})
            return
        with component._network_lock:
            if not self._valid(session):
                return
            with component._lock:
                if self.current is not session or session['cancelled'] or component._stopped:
                    return
                previous = component.store.configuration()
                if previous.get('appId'):
                    session['snapshot'].update(state='error', verificationUrl='', qrDataUrl='', qrModules=0, expiresAt=0,
                                               message='当前实例已有机器人，扫码结果未覆盖现有配置')
                    transport, session['transport'] = session['transport'], None
                    self._retire(transport)
                    return
                component.store.configure(dict(instanceName=session['name'], appId=app_id,
                                               secret=secret, desiredConnected=False))
                session['committed'] = True
                session['snapshot'].update(state='connecting', verificationUrl='', qrDataUrl='', qrModules=0, expiresAt=0,
                                           message='机器人已关联，正在连接飞书')
                transport, session['transport'] = session['transport'], None
                generation = component._generation
                session['connect_baseline'] = generation
            self._retire(transport)
            try:
                if not self._valid(session):
                    return
                component._connect(expected_generation=generation)
                if not self._valid(session):
                    self.cancel(session['owner'], '扫码接入已取消；机器人配置已保存，可手动连接', expected_session=session)
                    return
                with component._lock:
                    if self.current is not session or session['cancelled']:
                        return
                    config = component.store.configuration()
                    config['desiredConnected'] = True
                    component.store.configure(config)
                state, message = 'complete', '机器人已关联并连接；消息接收仍取决于飞书权限和长连接配置'
            except Exception:
                state, message = 'error', '机器人已关联，但连接失败；可检查飞书权限和网络后手动连接'
            with component._lock:
                if self.current is session and not session['cancelled'] and not component._stopped:
                    session['snapshot'].update(state=state, message=message)
