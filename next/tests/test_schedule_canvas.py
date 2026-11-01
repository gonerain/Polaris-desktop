"""End-to-end directory schedule mounting through the generic desktop approval UI."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]

if __name__ != '__main__':
    class ScheduleCanvasProcessTests(unittest.TestCase):
        def test_schedule_canvas_approval_and_task_persistence(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import json
    import tempfile
    import time
    import threading
    from PySide6.QtCore import QPoint, QPointF, Qt, QCoreApplication, QEvent
    from PySide6.QtGui import QGuiApplication, QCursor, QKeyEvent
    from PySide6.QtTest import QTest
    from polaris_platform.bootstrap import build
    from polaris_platform.component import Component
    from polaris_platform.desktop import WindowHost, Canvas, Manager

    def find(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            match = find(child, name)
            if match is not None:
                return match
        return None

    class ScheduleCanvasIntegration(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.directory = tempfile.TemporaryDirectory()
            config = json.loads((ROOT / 'config.schedule.json').read_text())
            plugin = ROOT / 'components' / 'schedule'
            manifest = json.loads((plugin / 'manifest.json').read_text())
            manifest['entry']['kwargs'] = {'data_dir': self.directory.name}
            config['components'][-1].update(manifest=manifest)
            self.runtime = build(config, ROOT)
            self.host = WindowHost(runtime=self.runtime)
            self.canvas = Canvas(runtime=self.runtime, collapse_delay=1500)
            self.manager = Manager(self.runtime)
            for identity, component in [('window', self.host), ('canvas', self.canvas), ('manager', self.manager), ('user', Component())]:
                self.runtime.install({'id': identity, 'name': identity, 'version': '1', 'platformApi': 1,
                    'entry': {'mode': 'inprocess'}}, lambda c=component: c)
                self.runtime.start_component(identity)
            for target in ('window', 'canvas'):
                for operation in self.runtime.status(target)['description']['operations']:
                    self.runtime.grant('user', target, operation)
            self.context = self.runtime.user_context('user')
            self.runtime.client('user').call('canvas', 'show', context=self.context)
            self.window = self.host._views[self.canvas.handle]
            self.wait(self.window.isVisible)
            QTest.qWait(30)

        def tearDown(self):
            self.wait(lambda: not self.canvas._workers)
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'], force=True)
            QTest.qWait(30)
            self.directory.cleanup()

        def wait(self, condition):
            end = time.monotonic() + 4
            while not condition() and time.monotonic() < end:
                QTest.qWait(10)
            self.assertTrue(condition(), self.manager.bridge.notice)

        def click(self, name, window=None):
            window = window or self.window
            item = find(window.contentItem(), name)
            self.assertIsNotNone(item, name)
            self.assertTrue(item.isVisible(), name)
            point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
            self.assertGreaterEqual(point.y(), 0, name)
            self.assertLess(point.y(), window.height(), name + ' must fit the visible window')
            QCursor.setPos(window.mapToGlobal(QPoint(round(point.x()), round(point.y()))))
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(30)
            return item

        def mount_by_picker(self):
            self.click('chooseComponentView')
            self.wait(lambda: find(self.window.contentItem(), 'componentViewChoice') is not None)
            self.click('componentViewChoice')
            self.wait(lambda: (self.manager.bridge.planJson != '[]' and not self.manager.bridge.busy) or bool(self.canvas.status()['mounts']))
            if self.manager.bridge.planJson != '[]':
                permissions = json.loads(self.manager.bridge.planJson)
                self.assertFalse(any(row['name'] in ('reorder', 'organize_day', 'move_overdue') for row in permissions))
                self.wait(lambda: find(self.manager._view.contentItem(), 'confirmPermission') is not None or bool(self.canvas.status()['mounts']))
                if not self.canvas.status()['mounts']:
                    self.click('confirmPermission', self.manager._view)
            self.wait(lambda: bool(self.canvas.status()['mounts']) and self.canvas.status()['mounts'][0]['state'] == 'mounted')
            self.wait(lambda: find(self.window.contentItem(), 'quickAdd') is not None)

        def test_stopped_component_rejects_delayed_gui_creation(self):
            self.mount_by_picker()
            component = self.runtime.component_instance('org.polaris.schedule')
            presentation = component._presentation
            context = next(iter(presentation._views.values()))[2]._context
            original = presentation.dispatcher.run
            waiting, gate = threading.Event(), threading.Event()
            errors = []
            def delayed(function):
                from PySide6.QtCore import QThread
                if QThread.currentThread() != self.app.thread():
                    waiting.set()
                    if not gate.wait(3):
                        raise RuntimeError('test did not resume GUI creation')
                return original(function)
            presentation.dispatcher.run = delayed
            parent = find(self.window.contentItem(), 'componentViewContent')
            def request():
                try:
                    component.create_view('main', parent, context)
                except Exception as error:
                    errors.append(error)
            worker = threading.Thread(target=request)
            worker.start()
            try:
                self.wait(waiting.is_set)
                self.runtime.stop_component('org.polaris.schedule')
                gate.set()
                self.wait(lambda: not worker.is_alive())
                self.assertTrue(errors)
                self.assertEqual(getattr(errors[0], 'code', None), 'stale_instance')
                self.assertFalse(presentation._views)
                self.assertIsNone(component._presentation)
            finally:
                gate.set()
                presentation.dispatcher.run = original
                self.wait(lambda: not worker.is_alive())

        def test_config_picker_approval_add_collapse_remove_remount(self):
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.mount_by_picker()
            self.window.requestActivate()
            QTest.qWait(30)
            self.click('quickAdd')
            for char in 'From canvas':
                QCoreApplication.sendEvent(self.window, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, char))
                QCoreApplication.sendEvent(self.window, QKeyEvent(QEvent.KeyRelease, 0, Qt.NoModifier, char))
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(50)
            data = json.loads((Path(self.directory.name) / 'schedule.json').read_text())
            self.assertEqual(data['tasks'][0]['title'], 'From canvas')
            self.click('canvasCollapseView')
            self.assertEqual(self.runtime.status('org.polaris.schedule')['state'], 'running')
            self.click('canvasCollapseView')
            self.click('canvasUnmountView')
            self.wait(lambda: not self.canvas.status()['mounts'])
            self.mount_by_picker()
            self.wait(lambda: find(self.window.contentItem(), 'completeTask_0') is not None)
            self.assertEqual(json.loads((Path(self.directory.name) / 'schedule.json').read_text())['tasks'], data['tasks'])
            self.window.grabWindow().save('/tmp/polaris-schedule-canvas.png')

    unittest.main()
