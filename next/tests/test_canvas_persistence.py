"""Real canvas mounting and user-input restoration against the runtime boundary."""
import tempfile
import unittest
from pathlib import Path

import importlib.util
import os
import subprocess
import sys

if __name__ != '__main__':
    class CanvasPersistenceProcessTests(unittest.TestCase):
        def test_canvas_owned_layout_and_real_input_restoration(self):
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        def test_independent_hosts_use_the_canvas_data_directory(self):
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            with tempfile.TemporaryDirectory() as directory:
                for mode in ('first', 'second'):
                    result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                        env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                                 CANVAS_HOST_MODE=mode, CANVAS_HOST_DIR=directory),
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QCursor
    from PySide6.QtTest import QTest
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.desktop import Canvas, WindowHost, Pet


    class CanvasPersistenceTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.directory = tempfile.TemporaryDirectory()
            self.runtime = build(default_config())
            self.host = WindowHost(runtime=self.runtime)
            for name, factory in [('user', Component), ('pet', lambda: Pet(runtime=self.runtime)), ('window', lambda: self.host),
                                  ('canvas', lambda: Canvas(runtime=self.runtime, data_dir=self.directory.name))]:
                self.runtime.install(dict(id=name, name=name, version='1', platformApi=1, entry=dict(mode='inprocess')), factory)
                self.runtime.start_component(name)
            self.runtime.install_directory(Path(__file__).resolve().parents[1] / 'examples/counter')
            self.runtime.start_component('org.example.counter')
            for target in ('window', 'canvas', 'pet', 'org.example.counter'):
                for operation in self.runtime.status(target)['description']['operations']:
                    self.runtime.grant('user', target, operation)
            for operation in ('show', 'status'):
                self.runtime.grant('pet', 'canvas', operation)
            for operation in ('status', 'show', 'create'):
                self.runtime.grant('pet', 'window', operation)
            self.user = self.runtime.user_context('user')
            self.canvas = self.runtime.component_instance('canvas')
            self.call('show')

        def call(self, operation, params=None):
            return self.runtime.client('user').call('canvas', operation, params, context=self.user)

        def wait(self, condition):
            for _ in range(250):
                if condition():
                    return
                QTest.qWait(10)
            self.assertTrue(condition())

        def tearDown(self):
            self.wait(lambda: not self.canvas._workers)
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'], persist=False)
            QTest.qWait(20)
            self.directory.cleanup()

        def restart(self):
            self.wait(lambda: not self.canvas._workers)
            self.runtime.stop_component('canvas', persist=False)
            self.runtime.start_component('canvas')
            self.canvas = self.runtime.component_instance('canvas')
            self.runtime.client('pet').call('canvas', 'show', {'anchor': {'x': 34, 'y': 56}}, context=self.runtime.user_context('pet'))
            QTest.qWait(20)

        def test_restart_restores_only_from_authorized_local_input(self):
            mounts = [self.call('mount', {'target': 'org.example.counter'})['mountId'] for _ in range(2)]
            self.wait(lambda: all(r['state'] == 'mounted' for r in self.canvas.mounts.values()))
            geometry = dict(x=71, y=53, width=415, height=260, collapsed=True)
            self.call('layout', dict(mountId=mounts[0], **geometry))
            window = self.host._views[self.canvas.handle]
            window.resize(1010, 740)
            QTest.qWait(300)
            original = self.canvas._storage.path.read_text()
            self.restart()
            self.assertEqual(self.canvas.size, (1010, 740))
            self.assertFalse(self.canvas.mounts, 'Pet show must not borrow canvas authority')
            for operation in ('status', 'create', 'show'):
                self.runtime.grant('canvas', 'window', operation)
            self.canvas.actions.pointerEntered()
            self.wait(lambda: len(self.canvas.mounts) == 2 and all(r['state'] == 'unavailable' for r in self.canvas.mounts.values()))
            self.assertEqual(self.canvas._storage.path.read_text(), original)
            for operation in self.runtime.status('org.example.counter')['description']['operations']:
                self.runtime.grant('canvas', 'org.example.counter', operation)
            for operation in ('status', 'create', 'show'):
                self.runtime.grant('canvas', 'window', operation)
            self.canvas.actions.pointerEntered()
            self.wait(lambda: len(self.canvas.mounts) == 2 and all(r['state'] == 'mounted' for r in self.canvas.mounts.values()))
            self.assertIn(geometry, [r['layout'] for r in self.canvas.mounts.values()])
            self.call('show')
            self.assertEqual(len(self.canvas.mounts), 2)
            self.runtime.stop_component('org.example.counter', persist=False)
            self.canvas._check_mounts()
            self.wait(lambda: not self.canvas.mounts)
            self.assertEqual(len(self.canvas._storage.entries), 2)
            self.runtime.start_component('org.example.counter')
            self.canvas.actions.pointerEntered()
            self.wait(lambda: len(self.canvas.mounts) == 2 and all(r['state'] == 'mounted' for r in self.canvas.mounts.values()))
            self.call('unmount', {'mountId': next(iter(self.canvas.mounts))})
            self.assertEqual(len(self.canvas._storage.entries), 1)

        def test_real_pet_click_and_first_canvas_hover_restore(self):
            self.call('mount', {'target': 'org.example.counter'})
            self.wait(lambda: all(r['state'] == 'mounted' for r in self.canvas.mounts.values()))
            self.restart()
            self.call('hide')
            for operation in ('status', 'create', 'show'):
                self.runtime.grant('canvas', 'window', operation)
            for operation in self.runtime.status('org.example.counter')['description']['operations']:
                self.runtime.grant('canvas', 'org.example.counter', operation)
            self.runtime.grant('pet', 'canvas', 'dismissed', kind='event')
            self.runtime.grant('pet', 'window', 'hide')
            self.runtime.grant('pet', 'pet', 'show')
            self.runtime.grant('pet', 'pet', 'hide')
            self.runtime.client('user').call('pet', 'show', context=self.user)
            pet = self.runtime.component_instance('pet')
            window = self.host._views[pet.handle]
            def find(item):
                if item.objectName() == 'petHitArea':
                    return item
                for child in item.childItems():
                    found = find(child)
                    if found is not None:
                        return found
            hit = find(window.rootObject())
            point = hit.mapToScene(QPointF(hit.width() / 2, hit.height() / 2)).toPoint()
            QCursor.setPos(window.mapToGlobal(point))
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            self.wait(lambda: self.canvas.session_id is not None and not pet.bridge.busy)
            canvas_window = self.host._views[self.canvas.handle]
            point = QPoint(100, 100)
            QCursor.setPos(canvas_window.mapToGlobal(point))
            QTest.mouseMove(canvas_window, point)
            self.wait(lambda: len(self.canvas.mounts) == 1 and all(r['state'] == 'mounted' for r in self.canvas.mounts.values()))

    def exercise_host():
        import time
        config = default_config()
        for identity, factory in [('window', 'create_window'), ('canvas', 'create_canvas'), ('pet', 'create_pet')]:
            config['components'].append(dict(autostart=True, trustedBindings=True, manifest=dict(
                id=identity, name=identity, version='1', platformApi=1,
                entry=dict(mode='inprocess', factory='polaris_platform.desktop:' + factory, kwargs={'runtime': {'runtime': True}}))))
        config['components'].append(dict(directory=str(Path(__file__).resolve().parents[1] / 'examples/counter'), autostart=True))
        app = QGuiApplication.instance() or QGuiApplication([])
        app.setQuitOnLastWindowClosed(False)
        runtime = build(config, state_dir=os.environ['CANVAS_HOST_DIR'])
        for identity in ('window', 'canvas', 'pet', 'org.example.counter'):
            if runtime.status(identity)['state'] != 'running':
                runtime.start_component(identity)
        canvas = runtime.component_instance('canvas')
        host = runtime.component_instance('window')
        pet = runtime.component_instance('pet')
        def wait(condition):
            deadline = time.monotonic() + 4
            while not condition() and time.monotonic() < deadline:
                QTest.qWait(10)
            assert condition(), (canvas.status(), canvas._storage.entries, runtime.authorization.scope('canvas'))
        if os.environ['CANVAS_HOST_MODE'] == 'first':
            for subject, targets in [('canvas', ('window', 'org.example.counter')), ('pet', ('window', 'canvas', 'pet'))]:
                for target in targets:
                    for operation in runtime.status(target)['description']['operations']:
                        runtime.grant(subject, target, operation)
            runtime.grant('pet', 'canvas', 'dismissed', kind='event')
        runtime.client('pet').call('pet', 'show', context=runtime.user_context('pet'))
        window = host._views[pet.handle]
        def find(item, name):
            if item.objectName() == name:
                return item
            for child in item.childItems():
                found = find(child, name)
                if found is not None:
                    return found
        hit = find(window.rootObject(), 'petHitArea')
        point = hit.mapToScene(QPointF(hit.width() / 2, hit.height() / 2)).toPoint()
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        wait(lambda: canvas.session_id is not None and not pet.bridge.busy)
        window = host._views[canvas.handle]
        QTest.qWait(40)
        point = QPoint(100, 100)
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseMove(window, point)
        if os.environ['CANVAS_HOST_MODE'] == 'first':
            context = runtime.user_context('canvas')
            descriptor = runtime.status('org.example.counter')['description']['views'][0]
            result = canvas.mount({'target': 'org.example.counter', 'descriptor': descriptor}, context)
            canvas.set_layout(dict(mountId=result['mountId'], x=43, y=67, width=390, height=245, collapsed=True), context)
            window.resize(960, 710)
            QTest.qWait(300)
        else:
            wait(lambda: len(canvas.mounts) == 1 and all(r['state'] == 'mounted' for r in canvas.mounts.values()))
            assert canvas.size == (960, 710), canvas.size
            assert next(iter(canvas.mounts.values()))['layout'] == dict(x=43, y=67, width=390, height=245, collapsed=True)
            runtime.client('pet').call('canvas', 'show', context=runtime.user_context('pet'))
            assert len(canvas.mounts) == 1
        assert canvas._storage.path.parent == runtime.component_data_directory('canvas')
        wait(lambda: not canvas._workers)
        for row in reversed(runtime.snapshot()):
            if row['state'] == 'running':
                runtime.stop_component(row['id'], persist=False)
        QTest.qWait(20)

    if os.environ.get('CANVAS_HOST_MODE'):
        exercise_host()
    else:
        unittest.main()
