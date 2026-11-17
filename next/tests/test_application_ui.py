"""Application packages own their QML and invoke real components as their principal."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

if __name__ != '__main__':
    class ApplicationUIProcessTests(unittest.TestCase):
        def test_own_ui_bindings_and_authority(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import json
    import tempfile
    import time
    import threading
    from unittest.mock import patch
    from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl, QMetaObject, QCoreApplication, QEvent
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest, QSignalSpy
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.desktop import Canvas, WindowHost, Manager

    def find(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            result = find(child, name)
            if result is not None: return result
        return None

    class OwnApplicationTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.qt = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.runtime = build(default_config(), state_dir=Path(self.temp.name) / 'runtime')
            self.window_host = WindowHost(runtime=self.runtime)
            self.canvas = Canvas(runtime=self.runtime, collapse_delay=100000)
            self.manager = Manager(self.runtime)
            for identity, component in [('window', self.window_host), ('canvas', self.canvas), ('manager', self.manager), ('user', Component())]:
                self.runtime.install(dict(id=identity, name=identity, version='1', platformApi=1,
                    entry={'mode': 'inprocess'}), lambda c=component: c)
                self.runtime.start_component(identity)
            self.runtime.install_directory(ROOT / 'examples' / 'text-studio' / 'component')
            self.runtime.start_component('org.example.text-tools')
            for target in ('window', 'canvas'):
                for operation in self.runtime.status(target)['description']['operations']:
                    self.runtime.grant('user', target, operation)
            self.runtime.client('user').call('canvas', 'show', context=self.runtime.user_context('user'))
            self.window = self.window_host._views[self.canvas.handle]
            self.host = self.canvas.application_host
            self.host.installDirectory(str(ROOT / 'examples' / 'text-studio' / 'application'))
            self.assertFalse(self.host.error, self.host.error)
            self.app_id = self.host._selected
            self.view = self.host._views[self.app_id]
            self.wait(lambda: self.view.root.width() > 500)
            self.stable = self.runtime.status('org.example.text-tools')['instanceId']

        def tearDown(self):
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'], force=True, persist=False)
            for _ in range(5):
                self.qt.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.temp.cleanup()
            sys.modules.pop('text_tools', None)

        def wait(self, predicate, timeout=5):
            deadline = time.monotonic() + timeout
            while not predicate() and time.monotonic() < deadline:
                self.qt.processEvents()
                QTest.qWait(5)
            self.assertTrue(predicate(), self.host.error)

        def click(self, name, window=None):
            window = window or self.window
            item = find(window.contentItem(), name)
            self.assertIsNotNone(item, name)
            point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(20)
            return item

        def connect(self, alias='tidy', choice=1):
            popup = self.window.rootObject().findChild(QObject, 'applicationConnectionsDialog')
            if not popup.property('visible'): self.click('applicationConnectionsToggle')
            combo = find(self.window.contentItem(), 'applicationBinding_' + alias)
            self.assertEqual(combo.property('currentIndex'), 0)
            point = combo.mapToScene(QPointF(combo.width()/2, combo.height()/2))
            QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.keyClick(self.window, Qt.Key_Down)
            for _ in range(choice - 1): QTest.keyClick(self.window, Qt.Key_Down)
            QTest.keyClick(self.window, Qt.Key_Return)
            self.wait(lambda: alias in self.host.store.load(self.app_id).bindings)
            self.assertFalse(self.runtime.authorization.scope(self.app_id))

        def approve(self):
            self.wait(lambda: not self.manager.bridge.busy and self.manager.bridge._pending_plan is not None)
            self.assertEqual(self.host._selected, self.app_id)
            self.assertFalse(self.window.rootObject().property('settingsOpen'))
            self.click('confirmApplicationPermission')
            self.wait(lambda: not self.host.busy)
            popup = self.window.rootObject().findChild(QObject, 'applicationConnectionsDialog')
            self.wait(lambda: popup.property('stage') == 'confirmed')
            self.click('finishApplicationPermission')

        def test_own_qml_real_gui_connection_permission_call_and_local_logic(self):
            root = self.view.root
            self.assertEqual(root.objectName(), 'textStudioApplication')
            self.assertIsNone(self.view.context.contextProperty('canvasActions'))
            self.assertIn(self.app_id, self.view.engine.offlineStoragePath())
            editor = find(root, 'studioEditor')
            editor.setProperty('text', '  今天   整理会议记录  \n\n  明天  完成文档  ')
            self.assertEqual(root.property('characters'), len(editor.property('text')))
            self.connect('tidy')
            self.connect('keywords')
            self.click('closeApplicationConnections')
            self.click('studioTidy')
            self.wait(lambda: self.manager.bridge._pending_plan is not None)
            self.assertFalse(root.property('output'))
            self.assertFalse(self.runtime.authorization.scope(self.app_id))
            self.approve()
            self.wait(lambda: root.property('output') == '今天 整理会议记录\n明天 完成文档')
            self.assertEqual(json.loads(self.host.result)['origin'], self.app_id)
            capture = os.environ.get('POLARIS_APPLICATION_CAPTURE')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                QTest.qWait(60)
                self.window.grabWindow().save(str(Path(capture) / 'text-studio.png'))
            self.click('workspaceEntry')
            self.assertFalse(self.view.bridge.active)
            rejected = QSignalSpy(self.view.bridge.failed)
            self.view.bridge.call('tidy', {'text': 'hidden'}, 'hidden')
            self.assertEqual(rejected.count(), 1)
            self.click('applicationEntry_' + self.app_id)
            self.assertIs(self.host._views[self.app_id], self.view)
            self.assertEqual(editor.property('text'), '  今天   整理会议记录  \n\n  明天  完成文档  ')
            self.click('studioClear')
            self.assertEqual(root.property('characters'), 0)

        def test_connections_popup_keeps_application_geometry_and_header_entry(self):
            surface = find(self.window.contentItem(), 'customApplicationSurface')
            popup = self.window.rootObject().findChild(QObject, 'applicationConnectionsDialog')
            for width in (1300, 720, 360):
                self.window.resize(width, 760)
                QTest.qWait(25)
                geometry = (surface.y(), surface.height(), self.view.root.height())
                toggle = find(self.window.contentItem(), 'applicationConnectionsToggle')
                dismiss = find(self.window.contentItem(), 'dismissCanvas')
                self.assertLess(toggle.mapToScene(QPointF()).x(), dismiss.mapToScene(QPointF()).x())
                self.assertEqual(toggle.mapToScene(QPointF()).y(), dismiss.mapToScene(QPointF()).y())
                self.click('applicationConnectionsToggle')
                self.assertTrue(popup.property('visible'))
                self.assertEqual(geometry, (surface.y(), surface.height(), self.view.root.height()))
                self.assertLessEqual(popup.property('width'), width - 32)
                capture = os.environ.get('POLARIS_APPLICATION_CAPTURE')
                if capture:
                    Path(capture).mkdir(parents=True, exist_ok=True)
                    self.window.grabWindow().save(str(Path(capture) / f'connections-dialog-{width}.png'))
                self.click('closeApplicationConnections')
                self.assertFalse(popup.property('visible'))
                self.assertEqual(geometry, (surface.y(), surface.height(), self.view.root.height()))

        def test_authorization_result_stays_in_dialog_and_repeated_calls_are_silent(self):
            self.connect('tidy')
            self.click('closeApplicationConnections')
            popup = self.window.rootObject().findChild(QObject, 'applicationConnectionsDialog')
            surface = find(self.window.contentItem(), 'customApplicationSurface')
            geometry = (surface.y(), surface.height())
            plans = QSignalSpy(self.manager.bridge.planReady)
            results = QSignalSpy(self.manager.bridge.applicationPermissionFinished)
            self.view.bridge.call('tidy', {'text': 'first'}, 'first')
            self.wait(lambda: self.manager.bridge._pending_plan is not None and not self.manager.bridge.busy)
            self.assertEqual(popup.property('stage'), 'approval')
            self.assertEqual(geometry, (surface.y(), surface.height()))
            self.click('confirmApplicationPermission')
            self.wait(lambda: popup.property('stage') == 'confirmed' and not self.host.busy)
            self.assertTrue(popup.property('visible'))
            self.assertEqual(geometry, (surface.y(), surface.height()))
            self.assertFalse(find(self.window.contentItem(), 'canvasMessageBar').isVisible())
            self.assertIn('授权已确认', find(self.window.contentItem(), 'applicationPermissionResult').property('text'))
            capture = os.environ.get('POLARIS_APPLICATION_CAPTURE')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                self.window.grabWindow().save(str(Path(capture) / 'application-authorization-result.png'))
            self.click('finishApplicationPermission')
            for index in range(3):
                self.view.bridge.call('tidy', {'text': 'refresh'}, 'refresh-' + str(index))
                self.wait(lambda: self.host.state == 'done')
                self.assertFalse(popup.property('visible'))
                self.assertFalse(self.manager.bridge.notice)
                self.assertEqual(geometry, (surface.y(), surface.height()))
            self.assertEqual(plans.count(), 1)
            self.assertEqual(results.count(), 1)
            self.assertTrue(self.runtime.authorization.scope(self.app_id))

        def test_authorization_failure_and_cancel_remain_in_popup(self):
            self.connect('tidy')
            self.click('closeApplicationConnections')
            popup = self.window.rootObject().findChild(QObject, 'applicationConnectionsDialog')
            surface = find(self.window.contentItem(), 'customApplicationSurface')
            geometry = (surface.y(), surface.height())
            self.view.bridge.call('tidy', {'text': 'failed'}, 'failed')
            self.wait(lambda: self.manager.bridge._pending_plan is not None and not self.manager.bridge.busy)
            with patch.object(self.manager.bridge, '_make_application_plan', side_effect=ValueError('授权校验失败')):
                self.click('confirmApplicationPermission')
                self.wait(lambda: popup.property('stage') == 'failed' and not self.host.busy)
            self.assertEqual(popup.property('resultMessage'), '授权校验失败')
            self.assertFalse(self.runtime.authorization.scope(self.app_id))
            self.assertEqual(geometry, (surface.y(), surface.height()))
            self.assertFalse(find(self.window.contentItem(), 'canvasMessageBar').isVisible())
            self.click('finishApplicationPermission')
            self.view.bridge.call('tidy', {'text': 'cancelled'}, 'cancelled')
            self.wait(lambda: self.manager.bridge._pending_plan is not None and not self.manager.bridge.busy)
            self.click('cancelApplicationPermission')
            self.wait(lambda: not self.host.busy)
            self.assertFalse(popup.property('visible'))
            self.assertFalse(self.runtime.authorization.scope(self.app_id))
            self.assertFalse(find(self.window.contentItem(), 'canvasMessageBar').isVisible())
            self.assertEqual(geometry, (surface.y(), surface.height()))

        def test_application_uses_common_runtime_lifecycle_and_owned_data(self):
            from polaris_platform.application import Application
            status = self.runtime.status(self.app_id)
            self.assertEqual(status['state'], 'running')
            self.assertEqual(status['componentType'], 'org.example.text-studio')
            self.assertEqual(status['instanceId'], self.app_id)
            component = self.runtime.application_component(self.app_id)
            self.assertIsInstance(component, Component)
            self.assertIsInstance(component, Application)
            self.assertEqual(self.runtime.component_data_directory(self.app_id),
                             self.host.application_data_directory(self.app_id))
            self.runtime.stop_component(self.app_id)
            self.qt.processEvents()
            self.assertFalse(self.view.bridge.active)
            self.assertFalse(self.view.root.isVisible())
            self.assertEqual(self.runtime.status(self.app_id)['state'], 'stopped')
            json.loads(self.host.connectionsJson)
            self.assertEqual(self.runtime.status(self.app_id)['state'], 'stopped')
            self.host.select(self.app_id)
            self.assertTrue(self.view.bridge.active)
            self.assertEqual(self.runtime.status(self.app_id)['state'], 'running')

        def test_queued_old_stop_cannot_close_reopened_application(self):
            stopper = threading.Thread(target=lambda: self.runtime.stop_component(self.app_id))
            stopper.start()
            stopper.join(3)
            self.assertFalse(stopper.is_alive())
            self.host.select(self.app_id)
            self.qt.processEvents()
            self.assertTrue(self.view.bridge.active)
            self.assertEqual(self.runtime.status(self.app_id)['state'], 'running')

        def test_contract_replacement_uses_other_type_and_local_operation(self):
            replacement = Component()
            replacement.operation('normalize', provides='org.example.text.tidy@1',
                                  applicationBinding='instance')(
                lambda params, context: dict(text='replacement:' + params['text'], origin=context.origin))
            self.runtime.install(dict(id='third.party.text', name='Alternative text', version='1',
                platformApi=1, entry={'mode': 'inprocess'}), lambda: replacement)
            self.runtime.start_component('third.party.text')
            rows = json.loads(self.host.connectionsJson)
            tidy = next(row for row in rows if row['alias'] == 'tidy')
            self.assertEqual(tidy['candidates'][0]['operation'], '整理文本')
            alternate = next(row for row in tidy['candidates'] if row['operation'] == 'normalize')
            self.connect('tidy')
            self.runtime.grant(self.app_id, self.stable, '整理文本')
            self.host.bindInstance('tidy', alternate['instanceId'], alternate['operation'])
            self.assertFalse(self.host.error, self.host.error)
            self.assertFalse(self.runtime.authorization.scope(self.app_id))
            binding = self.host.store.load(self.app_id).bindings['tidy']
            self.assertEqual(binding['operation'], 'normalize')
            self.assertEqual(binding['instanceId'], alternate['instanceId'])
            capture = os.environ.get('POLARIS_APPLICATION_CAPTURE')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                QTest.qWait(60)
                self.window.grabWindow().save(str(Path(capture) / 'application-connections.png'))
            self.view.bridge.call('tidy', {'text': 'hello'}, 'alternative')
            self.approve()
            self.assertEqual(json.loads(self.host.result), dict(text='replacement:hello', origin=self.app_id))

        def test_two_instances_and_revoke_require_fresh_confirmation(self):
            second = self.runtime.create_instance('org.example.text-tools')
            self.runtime.start_instance(second)
            self.connect('tidy', choice=2)
            self.click('closeApplicationConnections')
            self.assertEqual(self.host.store.load(self.app_id).bindings['tidy']['instanceId'], second)
            find(self.view.root, 'studioEditor').setProperty('text', '  second   instance  ')
            self.click('studioTidy')
            self.approve()
            self.assertEqual(json.loads(self.host.result)['instanceId'], second)
            old = self.runtime.application_context(self.app_id)
            self.host.revoke()
            self.assertFalse(self.runtime.authorization.scope(self.app_id))
            self.click('studioTidy')
            self.wait(lambda: self.manager.bridge._pending_plan is not None)
            self.assertFalse(self.manager.bridge._pending_plan['permissions'][0]['authorized'])
            self.manager.bridge.cancelView()
            self.wait(lambda: not self.host.busy)

        def test_real_directory_picker_opens_and_cancels_without_installing(self):
            before = len(self.host.store.list())
            self.manager.show()
            self.wait(lambda: self.manager.status()['visible'])
            self.click('installApplication')
            picker = self.window.rootObject().findChild(QObject, 'applicationDirectoryPicker')
            self.assertIsNotNone(picker)
            self.wait(lambda: picker.property('visible'))
            QMetaObject.invokeMethod(picker, 'reject')
            self.wait(lambda: not picker.property('visible'))
            self.assertEqual(len(self.host.store.list()), before)
            self.assertFalse(self.runtime.authorization.scope(self.app_id))

        def test_restored_package_and_connections_keep_identity_and_owned_data(self):
            self.connect('tidy')
            definition = self.host.store.load(self.app_id).as_dict()
            path = self.host.application_data_directory(self.app_id)
            (path / 'owned.txt').write_text('application-owned')
            offline = self.view.engine.offlineStoragePath()
            parent = self.view.parent
            directory = self.host.store.directory.parent
            self.host.close()
            self.host.configure(directory)
            self.host.attachView(parent)
            self.host.set_presentation_active(True)
            self.assertEqual(self.host.store.load(self.app_id).as_dict(), definition)
            restored = self.host._views[self.app_id]
            self.assertEqual(restored.engine.offlineStoragePath(), offline)
            self.assertTrue(restored.bridge.active)
            self.host.remove()
            self.assertEqual((path / 'owned.txt').read_text(), 'application-owned')

        def test_failed_definition_save_removes_only_uncommitted_package(self):
            self.host.remove()
            self.assertEqual(self.host.store.list(), [])
            with patch.object(self.host.store, 'save', side_effect=OSError('disk full')):
                self.host.installDirectory(str(ROOT / 'examples' / 'text-studio' / 'application'))
            self.assertIn('disk full', self.host.error)
            self.assertEqual(self.host.store.list(), [])
            self.assertEqual(list(self.host.packages.directory.iterdir()), [])

        def test_package_change_disables_cached_ui_and_broken_ui_remains_removable(self):
            app = self.host.store.load(self.app_id)
            entry = self.host.packages.load_verified(app)['entry']
            Path(entry).write_text('import QtQuick\nRectangle {}')
            self.host.set_presentation_active(True)
            self.assertFalse(self.view.bridge.active)
            self.assertIn('界面不可用', self.host.error)
            self.assertEqual(len(self.host.store.list()), 1)
            self.host.remove()
            self.assertEqual(self.host.store.list(), [])
            bad = Path(self.temp.name) / 'bad'; bad.mkdir()
            (bad / 'polaris-application.json').write_text(json.dumps(dict(id='bad', name='坏界面', version='1',
                entry={'adapter': 'qt-quick', 'file': 'Main.qml'}, requires={})))
            (bad / 'Main.qml').write_text('import QtQml\nQtObject {}')
            self.host.installDirectory(str(bad))
            self.assertEqual(len(self.host.store.list()), 1)
            self.assertIn('界面不可用', self.host.error)
            self.host.remove()
            self.assertEqual(self.host.store.list(), [])

        def test_busy_refusal_and_late_reply_after_hide_do_not_cross_view_lifecycle(self):
            self.connect('tidy')
            provider = self.runtime.component_instance('org.example.text-tools')
            entered, release = threading.Event(), threading.Event()
            original = provider._handlers['整理文本']
            def blocked(params, context):
                entered.set(); release.wait(4)
                return original(params, context)
            provider._handlers['整理文本'] = blocked
            replies = QSignalSpy(self.view.bridge.completed)
            self.view.bridge.call('tidy', {'text': 'first'}, 'first')
            self.wait(lambda: self.manager.bridge._pending_plan is not None)
            self.click('confirmApplicationPermission')
            self.wait(entered.is_set)
            generation = self.host._generation
            self.view.bridge.call('tidy', {'text': 'busy'}, 'busy')
            self.assertTrue(self.host.busy)
            self.assertEqual(generation, self.host._generation)
            self.host.select('')
            self.assertFalse(self.host.busy)
            release.set(); QTest.qWait(80)
            self.assertEqual(replies.count(), 0)
            self.host.select(self.app_id)
            self.host.remove()
            self.assertEqual(self.host.store.list(), [])

    unittest.main()
