"""Real Feishu native view and authority boundary with an isolated fake transport."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

if __name__ != '__main__':
    class FeishuBridgeProcessTests(unittest.TestCase):
        def test_native_bridge_authority_and_instance_isolation(self):
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import json
    import tempfile
    import threading
    import time
    from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, Qt, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/feishu'))
    from polaris_feishu_bot import FeishuBot
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.protocol import PlatformError

    class FakeTransport:
        def __init__(self, on_event):
            self.on_event = on_event
            self.requests = []
            self.closed = False
        def request(self, operation, params, timeout=35):
            self.requests.append((operation, dict(params), threading.get_ident()))
            if operation == 'connect': return {'connectionState': 'connected'}
            return {'success': True, 'messageId': 'om_fake_' + str(len(self.requests))}
        def close(self): self.closed = True

    import base64, io, qrcode, qrcode.image.svg
    MOCK_REGISTRATIONS = []
    for _index in range(2):
        _url = 'https://open.feishu.cn/registration?mock=' + str(_index) + 'long-mock-url-' * 34
        _qr = qrcode.QRCode(box_size=8, border=4)
        _qr.add_data(_url)
        _qr.make(fit=True)
        _stream = io.BytesIO()
        _qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(_stream)
        MOCK_REGISTRATIONS.append((_url, 'data:image/svg+xml;base64,' + base64.b64encode(_stream.getvalue()).decode(), _qr.modules_count + 8))

    class FakeRegistration:
        counter = 0
        def __init__(self, callback):
            self.callback = callback
            self.url, self.qr_source, self.modules = MOCK_REGISTRATIONS[FakeRegistration.counter % 2]
            FakeRegistration.counter += 1
            self.requests = []
            self.closed = False
        def request(self, operation, params=None, timeout=35):
            self.requests.append((operation, dict(params or {})))
            if operation == 'registration_start':
                self.callback('registration', dict(state='waiting', verificationUrl=self.url,
                    expiresAt=time.time() + 600, message='请扫码确认', qrDataUrl=self.qr_source, qrModules=self.modules))
                return {'started': True}
            return {}
        def emit(self, **payload): self.callback('registration', payload)
        def close(self): self.closed = True

    def find(item, name):
        if item.objectName() == name: return item
        for child in item.childItems():
            result = find(child, name)
            if result is not None: return result

    class NativeBridgeTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls): cls.qt = QGuiApplication([])
        def wait(self, predicate):
            end = time.monotonic() + 8
            while not predicate() and time.monotonic() < end:
                self.qt.processEvents()
                time.sleep(.005)
            self.assertTrue(predicate())
        def setUp(self):
            self.temporary = tempfile.TemporaryDirectory()
            self.directory = Path(self.temporary.name)
            self.registration_sessions = []
            def registration_factory(callback):
                session = FakeRegistration(callback)
                self.registration_sessions.append(session)
                return session
            self.runtime = build(default_config(), state_dir=self.directory / 'runtime')
            self.runtime.install(dict(id='viewer', name='查看者', version='1', platformApi=1,
                entry={'mode': 'inprocess'}), Component)
            self.runtime.start_component('viewer')
            self.runtime.install(dict(id='bot-fixture', name='飞书机器人测试', version='1', platformApi=1,
                entry={'mode': 'inprocess'}, instances={'mode': 'multiple'}),
                lambda instance_context: FeishuBot(instance_context, transport_factory=FakeTransport,
                    registration_transport_factory=registration_factory))
            self.runtime.start_component('bot-fixture')
            self.first = self.runtime.status('bot-fixture')['instanceId']
            self.second = self.runtime.create_instance('bot-fixture')
            self.runtime.start_instance(self.second)
            (self.directory / 'Root.qml').write_text('import QtQuick\nRectangle { width: 820; height: 640 }')
            self.windows = []
            self.views = {}
            self.handles = {}
            for identity in (self.first, self.second):
                for operation in ('create_view', 'release_view', 'status', 'read_messages'):
                    self.runtime.grant('viewer', identity, operation)
                window = QQuickView()
                window.setResizeMode(QQuickView.SizeRootObjectToView)
                window.setSource(QUrl.fromLocalFile(str(self.directory / 'Root.qml')))
                window.resize(820, 640)
                window.show()
                self.windows.append(window)
                result = self.call(identity, 'create_view', {'view': 'main', 'parent': window.rootObject()})
                component = self.runtime.component_instance(identity)
                item, bridge = component.presentation.views[result['handle']]
                item.setWidth(820)
                item.setHeight(640)
                self.views[identity] = (component, item, bridge)
                self.handles[identity] = result['handle']
            self.wait(lambda: all(not view[2]._polling for view in self.views.values()))
        def call(self, target, operation, params=None):
            return self.runtime.client('viewer').call(target, operation, params,
                context=self.runtime.user_context('viewer'))
        def click(self, identity, name):
            item = find(self.views[identity][1], name)
            if item is None:
                item = self.windows[0 if identity == self.first else 1].findChild(QObject, name)
            self.assertIsNotNone(item, name)
            self.assertTrue(item.property('enabled'), name)
            self.assertTrue(QMetaObject.invokeMethod(item, 'clicked', Qt.DirectConnection))
            self.qt.processEvents()
        def configure_first(self):
            component, item, bridge = self.views[self.first]
            self.click(self.first, 'feishuConfigure')
            window = self.windows[0]
            for name, value in [('feishuRobotName', '测试机器人'), ('feishuAppId', 'cli_native'),
                                ('feishuAppSecret', 'fake-secret-never-network')]:
                control = find(window.contentItem(), name) or window.findChild(QObject, name)
                self.assertIsNotNone(control)
                control.setProperty('text', value)
            self.click(self.first, 'feishuSaveConfiguration')
            self.wait(lambda: not bridge._busy and component.status()['configured'])
            self.wait(lambda: not bridge._polling)
            self.assertNotIn('fake-secret-never-network', bridge.stateJson)
            self.click(self.first, 'feishuConnect')
            self.wait(lambda: not bridge._busy and component.status()['connectionState'] == 'connected')
            self.wait(lambda: not bridge._polling)
            return component, item, bridge
        def tearDown(self):
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running': self.runtime.stop_component(row['id'], force=True, persist=False)
            for window in self.windows:
                window.close()
                window.deleteLater()
            for _ in range(5):
                self.qt.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.temporary.cleanup()

        def start_scan(self, identity=None):
            identity = identity or self.first
            component, item, bridge = self.views[identity]
            self.click(identity, 'feishuStartRegistration')
            self.wait(lambda: not bridge._busy and json.loads(bridge.stateJson)['registration']['state'] == 'waiting')
            return component, item, bridge, self.registration_sessions[-1]

        def test_registration_cancel_failure_retry_and_success_from_qml(self):
            component, item, bridge, session = self.start_scan()
            self.assertTrue(json.loads(bridge.stateJson)['registration']['qrImageSource'].startswith('data:image/svg+xml;base64,'))
            self.assertFalse(json.loads(self.views[self.second][2].stateJson)['registration']['verificationUrl'])
            bridge.refresh()
            self.wait(lambda: not bridge._polling)
            self.assertEqual(len(self.registration_sessions), 1)
            self.click(self.first, 'feishuCancelRegistration')
            self.wait(lambda: not bridge._busy and session.closed)
            self.assertFalse(component.status()['configured'])
            component, item, bridge, failed = self.start_scan()
            failed.emit(state='error', message='扫码创建失败，请重试')
            bridge.refresh()
            self.wait(lambda: json.loads(bridge.stateJson)['registration']['state'] == 'error')
            self.assertEqual(find(item, 'feishuStartRegistration').property('text'), '重新扫码')
            component, item, bridge, success = self.start_scan()
            success.emit(state='credentials', client_id='cli_scanned_mock', client_secret='mock-registration-secret', verifiedFeishu=True)
            self.wait(lambda: component.status()['configured'] and component.status()['connectionState'] == 'connected')
            bridge.refresh()
            self.wait(lambda: json.loads(bridge.stateJson)['configured'])
            self.assertEqual(component.status()['appId'], 'cli_scanned_mock')
            self.assertNotIn('mock-registration-secret', bridge.stateJson)
            self.assertEqual([row[0] for row in component._transport.requests], ['connect'])
            self.assertFalse(self.views[self.second][0].status()['configured'])
            self.assertFalse(find(item, 'feishuOnboarding').isVisible())

        def test_registration_survives_old_lifetime_then_preserves_server_expired_qr(self):
            from unittest.mock import patch
            component, item, bridge, session = self.start_scan()
            original_qr = json.loads(bridge.stateJson)['registration']['qrImageSource']
            original_clock = time.monotonic
            with patch('polaris_feishu_bot.registration.time.monotonic', side_effect=lambda: original_clock() + 7200):
                current = component.registration_snapshot(bridge.owner_id)
            self.assertEqual(current['state'], 'waiting')
            self.assertEqual(current['qrDataUrl'], session.qr_source)
            self.assertFalse(session.closed)
            session.emit(state='expired', message='二维码已过期，请手动刷新')
            bridge.refresh()
            self.wait(lambda: json.loads(bridge.stateJson)['registration']['state'] == 'expired')
            self.assertEqual(json.loads(bridge.stateJson)['registration']['qrImageSource'], original_qr)
            self.assertTrue(find(item, 'feishuRegistrationQr').isVisible())
            self.assertEqual(len(self.registration_sessions), 1)
            component, item, bridge, fresh = self.start_scan()
            fresh.emit(state='credentials', client_id='cli_after_refresh', client_secret='fake-secret', verifiedFeishu=True)
            self.wait(lambda: component.status()['connectionState'] == 'connected')

        def test_registration_success_after_old_lifetime_still_checks_authority(self):
            from unittest.mock import patch
            component, item, bridge, session = self.start_scan()
            original_clock = time.monotonic
            with patch('polaris_feishu_bot.registration.time.monotonic', side_effect=lambda: original_clock() + 7200):
                session.emit(state='credentials', client_id='cli_late_valid', client_secret='fake-secret', verifiedFeishu=True)
            self.wait(lambda: component.status()['connectionState'] == 'connected')
            self.assertEqual(component.status()['appId'], 'cli_late_valid')

        def test_registration_qr_works_with_different_qrcode_already_loaded(self):
            import types
            from unittest.mock import patch
            loaded = types.ModuleType('qrcode')
            loaded.__file__ = '/unrelated/application/qrcode/__init__.py'
            with patch.dict(sys.modules, {'qrcode': loaded}):
                component, item, bridge, session = self.start_scan()
                self.assertTrue(json.loads(bridge.stateJson)['registration']['qrImageSource'])
                self.assertIs(sys.modules['qrcode'], loaded)
                self.click(self.first, 'feishuCancelRegistration')
                self.wait(lambda: not bridge._busy and session.closed)

        def test_close_pending_scan_cancels_only_its_owner_and_discards_late_credentials(self):
            component, item, bridge, first_session = self.start_scan()
            other_component, other_item, other_bridge, second_session = self.start_scan(self.second)
            component.presentation.release(self.handles[self.first])
            self.assertTrue(first_session.closed)
            self.assertFalse(second_session.closed)
            self.assertNotEqual(first_session.url, second_session.url)
            self.assertNotEqual(first_session.qr_source, second_session.qr_source)
            first_session.emit(state='credentials', client_id='cli_late', client_secret='mock-late-secret', verifiedFeishu=True)
            self.qt.processEvents()
            self.assertFalse(component.status()['configured'])
            self.assertIsNone(component._transport)
            self.assertEqual(other_component.registration_snapshot(other_bridge.owner_id)['state'], 'waiting')

        def test_view_read_revocation_rejects_late_scan_success_before_next_refresh(self):
            component, item, bridge, session = self.start_scan()
            bridge.timer.stop()
            self.runtime.revoke('viewer', self.first, 'read_messages')
            session.emit(state='credentials', client_id='cli_revoked', client_secret='mock-revoked-secret', verifiedFeishu=True)
            self.wait(lambda: session.closed)
            self.assertFalse(component.status()['configured'])
            self.assertIsNone(component._transport)
            bridge.refresh()
            self.wait(lambda: not bridge._polling)
            self.assertFalse(json.loads(bridge.stateJson)['registration']['verificationUrl'])
            self.assertNotIn('mock-revoked-secret', bridge.stateJson)

        def test_local_native_configuration_and_send_are_async_and_instance_scoped(self):
            component, item, bridge = self.configure_first()
            self.assertFalse(self.views[self.second][0].status()['configured'])
            self.assertEqual(component.status()['connectionState'], 'connected')
            component.store.append('message', dict(messageId='om_incoming', chatId='oc_first',
                sender='小林', text='仅第一机器人消息', direction='incoming', createdAt='10:20'))
            bridge.refresh()
            self.wait(lambda: '仅第一机器人消息' in bridge.stateJson)
            self.views[self.second][2].refresh()
            self.wait(lambda: not self.views[self.second][2]._polling)
            self.assertNotIn('仅第一机器人消息', self.views[self.second][2].stateJson)
            bridge.selectConversation('oc_first')
            self.wait(lambda: not bridge._polling)
            find(item, 'feishuDraft').setProperty('text', '通过真实本机界面发送')
            self.click(self.first, 'feishuReply_om_incoming')
            sends_before = [row for row in component._transport.requests if row[0] in ('send', 'reply')]
            self.assertEqual(sends_before, [])
            self.click(self.first, 'feishuSend')
            self.wait(lambda: not bridge._busy and find(item, 'feishuDraft').property('text') == '')
            sends = [row for row in component._transport.requests if row[0] in ('send', 'reply')]
            self.assertEqual(len(sends), 1)
            self.assertNotEqual(sends[0][2], threading.get_ident())
            self.assertIsNone(self.views[self.second][0]._transport)

        def test_external_calls_cannot_forge_native_action_and_revocation_invalidates_ticket(self):
            component, item, bridge = self.configure_first()
            for operation in ('prepare_action', 'configure'):
                self.runtime.grant('viewer', self.first, operation)
            with self.assertRaises(PlatformError) as caught:
                self.call(self.first, 'prepare_action', {'operation': 'send', 'params': {'chat_id': 'oc_first', 'text': '不能伪造'}})
            self.assertEqual(caught.exception.code, 'permission_denied')
            with self.assertRaises(PlatformError) as caught:
                self.call(self.first, 'configure', {'name': '外部覆盖', 'app_id': 'cli_other', 'secret': 'fake'})
            self.assertEqual(caught.exception.code, 'permission_denied')
            ticket = component.authorize_from_view(bridge.local_input, 'send', dict(chat_id='oc_first', text='撤销后不能发送'))
            self.runtime.revoke(self.first, self.first, 'send')
            with self.assertRaises(PlatformError): component.execute_prepared(ticket)
            with self.assertRaises(PlatformError): component.execute_prepared(ticket)
            self.assertFalse(any(row[0] in ('send', 'reply') for row in component._transport.requests))
            self.assertEqual(component.status()['appId'], 'cli_native')

        def test_read_revocation_clears_cached_messages_and_disables_send(self):
            component, item, bridge = self.configure_first()
            component.store.append('message', dict(messageId='om_private', chatId='oc_private', sender='小林',
                text='撤权后清理的消息', direction='incoming'))
            bridge.refresh()
            self.wait(lambda: '撤权后清理的消息' in bridge.stateJson)
            find(item, 'feishuDraft').setProperty('text', '撤权时仍有草稿')
            find(item, 'feishuRecipient').setProperty('text', 'oc_private')
            self.runtime.revoke('viewer', self.first, 'read_messages')
            bridge.refresh()
            self.wait(lambda: not bridge._polling)
            state = json.loads(bridge.stateJson)
            self.assertEqual(state['messages'], [])
            self.assertEqual(state['conversations'], [])
            self.assertTrue(state['lastError'])
            self.assertFalse(find(item, 'feishuSend').property('enabled'))

    unittest.main()
