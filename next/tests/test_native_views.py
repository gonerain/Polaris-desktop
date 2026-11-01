"""Independent Qt-native plugin tests in a disposable application process."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

if __name__ != '__main__':
    class NativeViewProcessTests(unittest.TestCase):
        def test_native_directory_plugin_buttons_authority_and_lifecycle(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import tempfile
    from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QGuiApplication, QCursor
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest

    def _mouseMove(window, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseMove(window, point)

    def _mouseClick(window, button, modifiers, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseClick(window, button, modifiers, point)

    def _mousePress(window, button, modifiers, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mousePress(window, button, modifiers, point)

    def _mouseRelease(window, button, modifiers, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseRelease(window, button, modifiers, point)
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component

    def find_item(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = find_item(child, name)
            if found is not None:
                return found
        return None

    class NativePluginTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.runtime = build(default_config())
            self.runtime.install({'id': 'user', 'name': 'User', 'version': '1', 'platformApi': 1,
                                  'entry': {'mode': 'inprocess'}}, Component)
            self.runtime.start_component('user')
            self.runtime.install_directory(ROOT / 'examples' / 'counter')
            self.runtime.start_component('org.example.counter')
            for operation in ('get', 'increment', 'create_view', 'release_view'):
                self.runtime.grant('user', 'org.example.counter', operation)
            self.context = self.runtime.user_context('user')
            self.directory = tempfile.TemporaryDirectory()
            source = Path(self.directory.name) / 'root.qml'
            source.write_text("import QtQuick\nRectangle { width: 500; height: 350; color: 'white' }\n")
            self.window = QQuickView()
            self.window.setSource(QUrl.fromLocalFile(str(source)))
            self.window.show()
            QTest.qWait(40)

        def tearDown(self):
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'])
            self.window.close()
            import shiboken6
            shiboken6.delete(self.window)
            self.app.processEvents()
            self.directory.cleanup()

        def call(self, operation, params=None):
            return self.runtime.client('user').call('org.example.counter', operation, params,
                                                    context=self.context)

        def create_view(self):
            resource = self.call('create_view', {'view': 'main', 'parent': self.window.rootObject()})
            resource['item'].setWidth(340)
            resource['item'].setHeight(230)
            QTest.qWait(40)
            return resource

        def click(self, item):
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            _mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(30)

        def test_owned_qml_buttons_and_live_authorization(self):
            resource = self.create_view()
            increase = find_item(resource['item'], 'counterIncrease')
            decrease = find_item(resource['item'], 'counterDecrease')
            self.assertIsNotNone(increase)
            self.click(increase)
            self.assertEqual(self.call('get'), {'value': 1})
            self.click(decrease)
            self.assertEqual(self.call('get'), {'value': 0})
            self.runtime.revoke('user', 'org.example.counter', 'increment')
            self.click(increase)
            self.assertEqual(self.call('get'), {'value': 0})
            self.assertTrue(find_item(resource['item'], 'counterError').property('text'))

        def test_releasing_view_preserves_counter_business(self):
            resource = self.create_view()
            self.click(find_item(resource['item'], 'counterIncrease'))
            self.assertTrue(self.call('release_view', {'handle': resource['handle']})['released'])
            self.assertEqual(self.call('get'), {'value': 1})
            self.assertEqual(self.runtime.status('org.example.counter')['state'], 'running')
            replacement = self.create_view()
            self.assertEqual(find_item(replacement['item'], 'counterValue').property('text'), '1')
            self.runtime.stop_component('org.example.counter')
            QTest.qWait(40)
            self.assertFalse(self.window.rootObject().childItems())

    unittest.main()
