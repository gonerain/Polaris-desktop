"""Feishu native QML interactions; fake transport only, never real network sends."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

if __name__ != '__main__':
    class FeishuUIProcessTests(unittest.TestCase):
        def test_feishu_native_ui(self):
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/feishu'))
    def qr_image_source(url, with_modules=False):
        import base64, io, qrcode, qrcode.image.svg
        code = qrcode.QRCode(box_size=8, border=4)
        code.add_data(url)
        code.make(fit=True)
        stream = io.BytesIO()
        code.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(stream)
        source = 'data:image/svg+xml;base64,' + base64.b64encode(stream.getvalue()).decode()
        return (source, code.modules_count + 8) if with_modules else source
    from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QMetaObject, QPointF, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQml import QQmlExpression, qmlContext
    from PySide6.QtTest import QTest

    QML = Path(__file__).resolve().parents[1] / 'plugins/feishu/polaris_feishu_bot/Feishu.qml'

    class FakeBridge(QObject):
        changed = Signal()
        messageSent = Signal()
        def __init__(self, name='测试机器人'):
            super().__init__()
            self.calls = []
            self.state = dict(instanceName=name, appId='', hasSecret=False, configured=False,
                connectionState='disconnected', connectionLabel='未连接', busy=False, lastError='', notice='',
                conversations=[], messages=[], registration=dict(state='idle', verificationUrl='', qrImageSource='', message='', expiresAt=0))
        @Property(str, notify=changed)
        def stateJson(self): return json.dumps(self.state)
        def update(self, **values):
            self.state.update(values)
            self.changed.emit()
        @Slot()
        def startRegistration(self):
            self.calls.append(('startRegistration',))
            url = 'https://open.feishu.cn/registration?mock=' + 'long-mock-url-' * 34
            source, modules = qr_image_source(url, with_modules=True)
            self.update(registration=dict(state='waiting', verificationUrl=url, qrImageSource=source, qrModules=modules, message='请扫码并确认', expiresAt=9999999999))
        @Slot()
        def cancelRegistration(self):
            self.calls.append(('cancelRegistration',))
            self.update(registration=dict(state='cancelled', verificationUrl='', qrImageSource='', message='', expiresAt=0))
        @Slot()
        def openRegistrationLink(self): self.calls.append(('browser',))
        @Slot(str, str, str)
        def saveConfiguration(self, name, app_id, secret):
            self.calls.append(('save', name, app_id, bool(secret)))
            self.update(instanceName=name, appId=app_id, hasSecret=True, configured=True)
        @Slot()
        def connectBot(self): self.calls.append(('connect',))
        @Slot()
        def disconnectBot(self): self.calls.append(('disconnect',))
        @Slot()
        def refresh(self): self.calls.append(('refresh',))
        @Slot(str)
        def selectConversation(self, chat_id): self.calls.append(('select', chat_id))
        @Slot(str, str, str)
        def sendMessage(self, chat_id, text, reply_id): self.calls.append(('send', chat_id, text, reply_id))

    def find(item, name):
        if item.objectName() == name: return item
        for child in item.childItems():
            found = find(child, name)
            if found is not None: return found

    class FeishuNativeUITests(unittest.TestCase):
        @classmethod
        def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])
        def setUp(self):
            self.bridge = FakeBridge()
            self.window = self.make_window(self.bridge)
            self.root = self.window.rootObject()
        def make_window(self, bridge):
            view = QQuickView()
            view.setResizeMode(QQuickView.SizeRootObjectToView)
            view.rootContext().setContextProperty('feishuBot', bridge)
            view.setSource(QUrl.fromLocalFile(str(QML)))
            self.assertFalse(view.errors(), [error.toString() for error in view.errors()])
            view.resize(820, 640)
            view.show()
            QTest.qWait(30)
            return view
        def tearDown(self):
            self.window.close()
            self.window.deleteLater()
            self.app.processEvents()
        def control(self, name):
            item = find(self.window.contentItem(), name)
            if item is None: item = self.window.findChild(QObject, name)
            self.assertIsNotNone(item, name)
            return item
        def click(self, name):
            item = self.control(name)
            self.assertTrue(item.property('enabled'), name)
            self.assertTrue(QMetaObject.invokeMethod(item, 'clicked', Qt.DirectConnection))
            QTest.qWait(10)
        def ready(self):
            self.bridge.update(configured=True, hasSecret=True, appId='cli_test', connectionState='connected', connectionLabel='已连接',
                conversations=[dict(chatId='oc_test', title='项目讨论', lastText='收到的消息')],
                messages=[dict(messageId='om_test', chatId='oc_test', sender='小林', text='<b>普通文本</b>', createdAt='10:20', direction='incoming')])
            QTest.qWait(20)
            self.click('feishuConversation_oc_test')

        def test_scan_creation_is_explicit_cancel_retry_and_success(self):
            self.assertTrue(self.control('feishuStartRegistration').isVisible())
            self.assertEqual(self.bridge.calls, [])
            self.click('feishuStartRegistration')
            self.assertEqual(self.control('feishuRegistrationState').property('text'), '等待扫码确认')
            self.assertTrue(self.control('feishuRegistrationQr').isVisible())
            self.click('feishuRefresh')
            self.assertEqual(len([row for row in self.bridge.calls if row[0] == 'startRegistration']), 1)
            capture = os.environ.get('POLARIS_FEISHU_CAPTURE')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                QTest.qWait(100)
                self.window.grabWindow().save(str(Path(capture) / 'feishu-scan-waiting.png'))
                self.window.resize(380, 640)
                QTest.qWait(30)
                self.window.grabWindow().save(str(Path(capture) / 'feishu-scan-narrow.png'))
            self.click('feishuCancelRegistration')
            self.assertFalse(self.control('feishuRegistrationQr').isVisible())
            self.assertEqual(self.bridge.state['registration']['state'], 'cancelled')
            self.bridge.update(registration=dict(state='expired', verificationUrl='', qrImageSource='', message='二维码已过期', expiresAt=0))
            self.assertEqual(self.control('feishuStartRegistration').property('text'), '刷新二维码')
            self.click('feishuStartRegistration')
            self.bridge.update(registration=dict(state='error', verificationUrl='', qrImageSource='', message='官方注册暂不可用，请重试', expiresAt=0))
            self.assertEqual(self.control('feishuStartRegistration').property('text'), '重新扫码')
            self.click('feishuStartRegistration')
            self.bridge.update(configured=True, appId='cli_from_mock', hasSecret=True, connectionState='connected',
                registration=dict(state='complete', verificationUrl='', qrImageSource='', message='已完成', expiresAt=0))
            self.assertFalse(self.control('feishuOnboarding').isVisible())
            self.assertTrue(self.control('feishuMessages').isVisible())
            self.assertFalse(any(row[0] == 'send' for row in self.bridge.calls))

        def test_configuration_masks_secret_and_does_not_claim_connection(self):
            self.assertEqual(self.bridge.calls, [])
            self.assertFalse(self.control('feishuConnect').property('enabled'))
            self.click('feishuConfigure')
            secret = self.control('feishuAppSecret')
            self.assertTrue(QQmlExpression(qmlContext(secret), secret, 'echoMode === TextInput.Password').evaluate()[0])
            self.control('feishuRobotName').setProperty('text', '项目机器人')
            self.control('feishuAppId').setProperty('text', 'cli_project')
            secret.setProperty('text', 'not-a-real-secret')
            self.click('feishuSaveConfiguration')
            self.assertEqual(self.bridge.calls, [('save', '项目机器人', 'cli_project', True)])
            self.assertEqual(secret.property('text'), '')
            self.assertEqual(self.control('feishuLocalConfiguration').property('text'), '本地已配置')
            self.assertEqual(self.control('feishuConnectionState').property('text'), '未连接')
            self.assertFalse(self.control('feishuSend').property('enabled'))
            self.click('feishuConnect')
            self.assertEqual(self.bridge.calls[-1], ('connect',))
            self.assertNotIn('not-a-real-secret', self.bridge.stateJson)
            self.click('feishuConfigure')
            self.assertTrue(self.control('feishuAppId').property('readOnly'))
            self.click('feishuCancelConfiguration')

        def test_send_and_reply_require_explicit_click_and_preserve_selected_endpoint(self):
            self.ready()
            self.control('feishuDraft').setProperty('text', '手动回复')
            QTest.qWait(30)
            self.assertFalse(any(row[0] == 'send' for row in self.bridge.calls))
            self.click('feishuReply_om_test')
            self.assertEqual(self.root.property('replyMessageId'), 'om_test')
            self.assertFalse(any(row[0] == 'send' for row in self.bridge.calls))
            self.click('feishuSend')
            self.assertEqual(self.bridge.calls[-1], ('send', 'oc_test', '手动回复', 'om_test'))
            self.click('feishuCancelReply')
            self.click('feishuSend')
            self.assertEqual(self.bridge.calls[-1], ('send', 'oc_test', '手动回复', ''))
            self.bridge.messageSent.emit()
            self.assertEqual(self.control('feishuDraft').property('text'), '')
            self.assertEqual(self.root.property('replyMessageId'), '')
            self.control('feishuDraft').setProperty('text', '失败时保留草稿')
            self.bridge.update(busy=True)
            self.assertFalse(self.control('feishuSend').property('enabled'))
            self.bridge.update(busy=False, connectionState='error', connectionLabel='连接失败', lastError='连接失败，请检查应用权限。')
            self.assertFalse(self.control('feishuSend').property('enabled'))
            self.assertEqual(self.control('feishuError').property('text'), '连接失败，请检查应用权限。')
            self.assertEqual(self.control('feishuDraft').property('text'), '失败时保留草稿')

        def test_compact_layout_and_instance_state_are_independent(self):
            self.ready()
            self.window.resize(380, 640)
            QTest.qWait(30)
            self.assertTrue(self.control('feishuConversationPicker').isVisible())
            self.assertFalse(self.control('feishuConversations').isVisible())
            send = self.control('feishuSend')
            bottom = send.mapToScene(QPointF(0, send.height())).y()
            self.assertLessEqual(bottom, self.window.height())
            self.assertGreater(send.width(), 40)
            capture = os.environ.get('POLARIS_FEISHU_CAPTURE')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                self.window.grabWindow().save(str(Path(capture) / 'feishu-narrow.png'))
            other_bridge = FakeBridge('另一个机器人')
            other_window = self.make_window(other_bridge)
            try:
                self.assertEqual(other_bridge.calls, [])
                self.assertEqual(other_window.rootObject().property('selectedChatId'), '')
                self.assertEqual(find(other_window.contentItem(), 'feishuIdentity').property('text'), '另一个机器人')
                self.assertEqual(self.root.property('selectedChatId'), 'oc_test')
            finally:
                other_window.close()
                other_window.deleteLater()
            capture = os.environ.get('POLARIS_FEISHU_CAPTURE')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                self.window.resize(820, 640)
                QTest.qWait(40)
                self.window.grabWindow().save(str(Path(capture) / 'feishu-main.png'))
                self.click('feishuConfigure')
                self.window.grabWindow().save(str(Path(capture) / 'feishu-settings.png'))

    unittest.main()
