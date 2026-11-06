import asyncio
import base64
from collections import deque
import gzip
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from polaris_feishu_bot import FeishuBot
from polaris_feishu_bot.registration import ADDONS, RegistrationError, is_registration_url, run_registration
from polaris_platform.protocol import PlatformError


class SDKRegistrationTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        from lark_oapi.ws.client import loop
        if not loop.is_running() and not loop.is_closed():
            loop.close()

    def scenario(self, polls, verify_success=True, begin=None):
        import httpx
        from lark_oapi.scene import registration as sdk
        records, urls, emitted = [], [], []
        responses = deque([{'supported_auth_methods': ['client_secret']}, begin or {
            'device_code': 'private-device', 'verification_uri_complete': 'https://open.feishu.cn/page/cli?user_code=dummy',
            'expires_in': 500, 'interval': 0}, *polls])
        async def post(client, url, **kwargs):
            if url.startswith('https://open.feishu.cn/open-apis/auth/'):
                records.append(('verify', kwargs))
                data = {'code': 0, 'tenant_access_token': 'private-token'} if verify_success else {'code': 10003}
            else:
                records.append((url, parse_qs(kwargs['content'])))
                data = responses.popleft()
            return SimpleNamespace(status_code=200, json=lambda: data)
        original = asyncio.sleep
        async def fast_sleep(_):
            await original(0)
        with patch.object(httpx.AsyncClient, 'post', new=post), patch.object(sdk.asyncio, 'sleep', new=fast_sleep):
            asyncio.run(run_registration(emitted.append, 'Test Bot'))
        return emitted, records

    def test_official_sdk_pending_slowdown_success_minimal_confirm_options(self):
        emitted, records = self.scenario([{'error': 'authorization_pending'}, {'error': 'slow_down'},
            {'client_id': 'cli_offline', 'client_secret': 'fake-only', 'user_info': {'tenant_brand': 'feishu'}}])
        self.assertEqual(emitted[-1]['state'], 'credentials')
        self.assertTrue(emitted[-1]['verifiedFeishu'])
        qr = next(value for value in emitted if value.get('verificationUrl'))
        self.assertGreaterEqual(qr['qrModules'], 21)
        self.assertTrue(qr['qrDataUrl'].startswith('data:image/svg+xml;base64,'))
        self.assertIn(b'<svg', base64.b64decode(qr['qrDataUrl'].split(',', 1)[1]))
        query = parse_qs(urlsplit(qr['verificationUrl']).query)
        encoded = query['addons'][0]
        decoded = json.loads(gzip.decompress(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))))
        self.assertEqual(decoded, ADDONS)
        self.assertEqual(query['createOnly'], ['true'])
        self.assertNotIn('user', decoded['scopes'])
        self.assertEqual(sum(key == 'verify' for key, _ in records), 1)
        safe = json.dumps([value for value in emitted if value['state'] != 'credentials'])
        self.assertNotIn('private-token', safe)
        self.assertNotIn('private-device', safe)

    def test_denied_expired_malformed_and_wrong_brand(self):
        cases = [({'error': 'access_denied', 'error_description': 'secret detail'}, 'error'),
                 ({'error': 'expired_token'}, 'expired'), ({'client_id': ['bad'], 'client_secret': 'fake'}, 'error'),
                 ({'client_id': 'cli_wrong', 'client_secret': 'fake', 'user_info': {'tenant_brand': 'lark'}}, 'error')]
        for response, expected in cases:
            with self.subTest(response=response):
                emitted, records = self.scenario([response])
                self.assertEqual(emitted[-1]['state'], expected)
                self.assertNotEqual(emitted[-1]['state'], 'credentials')
                self.assertNotIn('secret detail', json.dumps(emitted))
                self.assertFalse(any(key == 'verify' for key, _ in records))
        emitted, _ = self.scenario([], begin={'device_code': 'dummy', 'verification_uri_complete': 'https://evil.invalid/', 'expires_in': 500})
        self.assertEqual(emitted[-1]['state'], 'error')

    def test_missing_brand_requires_fixed_feishu_auth_verification(self):
        emitted, records = self.scenario([{'client_id': 'cli_offline', 'client_secret': 'fake'}])
        self.assertEqual(emitted[-1]['state'], 'credentials')
        self.assertEqual([key for key, _ in records].count('verify'), 1)
        emitted, _ = self.scenario([{'client_id': 'cli_offline', 'client_secret': 'fake'}], verify_success=False)
        self.assertEqual(emitted[-1]['state'], 'error')

    def test_cancel_timeout_and_url_allowlist(self):
        async def register(**kwargs):
            await asyncio.Event().wait()
        async def run():
            emitted = []
            await run_registration(emitted.append, 'Test', timeout=.02, register=register)
            self.assertEqual(emitted[-1]['state'], 'expired')
            task = asyncio.create_task(run_registration(emitted.append, 'Test', register=register))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(run())
        for url in ['http://open.feishu.cn/', 'https://open.feishu.cn.evil.invalid/',
                    'https://user@open.feishu.cn/', 'https://open.feishu.cn:444/', 'javascript:evil()']:
            self.assertFalse(is_registration_url(url))


class RegistrationBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transports = []

    def bot(self, identity):
        transports = self.transports
        class Fake:
            def __init__(self, callback):
                self.callback, self.closed = callback, False
                transports.append(self)
            def request(self, operation, params):
                if operation == 'connect':
                    return {'connectionState': 'connected'}
                return {'started': True}
            def close(self):
                self.closed = True
        bot = FeishuBot({'instanceId': identity, 'dataDir': str(Path(self.temp.name) / identity)}, Fake, Fake)
        port = SimpleNamespace(id=identity)
        def call(target, operation, params, context):
            self.assertEqual(operation, 'registration_checkpoint')
            if getattr(port, 'revoked', False):
                raise PlatformError('permission_required', 'revoked')
            return {'active': True}
        port.call = call
        bot.start(port)
        self.addCleanup(bot.stop)
        return bot

    def start(self, bot, owner='owner'):
        bot.register_registration_owner(owner, lambda: None)
        bot.registration.start('Test Bot', owner, SimpleNamespace(request_id='local-request'))
        deadline = time.monotonic() + 2
        while bot.registration.current['transport'] is None and time.monotonic() < deadline:
            time.sleep(.005)
        return bot.registration.current, bot.registration.current['transport']

    @staticmethod
    def success(transport, app_id='cli_test'):
        transport.callback('registration', dict(state='credentials', client_id=app_id,
                           client_secret='private-secret', verifiedFeishu=True))

    def test_success_only_current_instance_saves_connects_and_never_exposes_secret(self):
        first, second = self.bot('first'), self.bot('second')
        session, transport = self.start(first)
        self.start(second, 'second-owner')
        self.success(transport)
        self.assertEqual(first.status()['connectionState'], 'connected')
        self.assertEqual(first.store.configuration()['appId'], 'cli_test')
        self.assertTrue(first.store.configuration()['desiredConnected'])
        self.assertFalse(second.status()['configured'])
        self.assertEqual(first.registration_snapshot('owner')['state'], 'complete')
        self.assertNotIn('private-secret', json.dumps(first.registration_snapshot('owner')))
        self.assertNotIn('verificationUrl', first.status())
        self.assertEqual((first.store.directory / 'configuration.json').stat().st_mode & 0o777, 0o600)

    def test_cancel_retry_stop_and_late_success_are_isolated(self):
        bot = self.bot('first')
        first, old = self.start(bot)
        bot.cancel_registration_owner('owner')
        self.success(old)
        self.assertFalse(bot.status()['configured'])
        new, transport = self.start(bot, 'new-owner')
        bot.cancel_registration_owner('owner')
        self.success(old)
        self.assertIs(bot.registration.current, new)
        self.assertFalse(bot.status()['configured'])
        bot.stop()
        self.success(transport)
        self.assertFalse(bot.store.configuration()['appId'])

    def test_viewer_revocation_and_existing_app_prevent_commit(self):
        bot = self.bot('first')
        session, transport = self.start(bot)
        bot.port.revoked = True
        self.success(transport)
        self.assertFalse(bot.status()['configured'])
        bot.port.revoked = False
        session, transport = self.start(bot)
        bot.registration.owners['owner'] = lambda: (_ for _ in ()).throw(PlatformError('permission_required', 'viewer read revoked'))
        self.success(transport)
        self.assertFalse(bot.status()['configured'])
        session, transport = self.start(bot)
        bot.store.configure(dict(instanceName='Existing', appId='cli_existing', secret='existing-secret', desiredConnected=False))
        self.success(transport)
        self.assertEqual(bot.store.configuration()['appId'], 'cli_existing')

    def test_delayed_old_begin_cannot_cancel_same_owner_retry(self):
        bot = self.bot('first')
        entered, release = threading.Event(), threading.Event()
        original = bot.registration._valid
        first = []
        def validity(session):
            if not first:
                first.append(session)
                entered.set()
                release.wait(2)
                return False
            return original(session)
        bot.register_registration_owner('owner', lambda: None)
        with patch.object(bot.registration, '_valid', side_effect=validity):
            bot.registration.start('First', 'owner', SimpleNamespace(request_id='request'))
            self.assertTrue(entered.wait(2))
            latest, transport = self.start(bot)
            release.set()
            time.sleep(.03)
            self.assertIs(bot.registration.current, latest)
            self.assertFalse(latest['cancelled'])
            self.success(transport)
            self.assertEqual(bot.store.configuration()['appId'], 'cli_test')

    def test_cancel_after_save_disables_future_connection_intent(self):
        bot = self.bot('first')
        session, transport = self.start(bot)
        def connect(**kwargs):
            bot.cancel_registration_owner('owner')
        with patch.object(bot, '_connect', side_effect=connect):
            self.success(transport)
        self.assertEqual(bot.store.configuration()['appId'], 'cli_test')
        self.assertFalse(bot.store.configuration()['desiredConnected'])
