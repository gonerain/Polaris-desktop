"""Native attach cancellation across actual component/window lifecycle changes."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


if __name__ != '__main__':
    class CanvasLifecycleProcessTests(unittest.TestCase):
        def test_pending_native_attach_cannot_outlive_its_instance_or_parent(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import threading
    import time
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.desktop import Canvas, WindowHost

    class NativeProvider(Component):
        def __init__(self):
            super().__init__()
            self.created = 0
            self.items = {}
            self.on_create = None
            self.operation('create_view', 'write')(self.create)
            self.operation('release_view', 'write')(self.release)

        def create(self, params, context):
            assert QThread.currentThread() == QGuiApplication.instance().thread()
            self.created += 1
            item = QQuickItem(params['parent'])
            item.setParent(params['parent'])
            handle = str(self.created)
            self.items[handle] = item
            if self.on_create is not None:
                self.on_create()
            return {'handle': handle, 'item': item}

        def release(self, params, context):
            item = self.items.pop(params['handle'], None)
            if item is not None:
                item.deleteLater()
            return {'released': item is not None}

    class AttachLifecycleTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.runtime = build(default_config())
            self.provider = NativeProvider()
            factories = {'user': Component, 'provider': lambda: self.provider,
                         'window': lambda: WindowHost(runtime=self.runtime),
                         'canvas': lambda: Canvas(runtime=self.runtime)}
            for identity, factory in factories.items():
                self.runtime.install({'id': identity, 'name': identity, 'version': '1',
                    'platformApi': 1, 'entry': {'mode': 'inprocess'}}, factory)
                self.runtime.start_component(identity)
            for identity in ('provider', 'window', 'canvas'):
                for operation in self.runtime.status(identity)['description']['operations']:
                    self.runtime.grant('user', identity, operation)
            self.context = self.runtime.user_context('user')
            self.client = self.runtime.client('user')
            self.canvas = self.runtime.component_instance('canvas')
            self.client.call('canvas', 'show', context=self.context)
            QTest.qWait(20)
            self.gate = threading.Event()
            self.waiting = threading.Event()
            self.original_run = self.canvas.dispatcher.run
            def gated_run(function):
                if QThread.currentThread() != self.app.thread():
                    self.waiting.set()
                    if not self.gate.wait(3):
                        raise RuntimeError('Test did not release native attach')
                return self.original_run(function)
            self.canvas.dispatcher.run = gated_run
            self.errors = []
            self.canvas.actions.failed.connect(lambda *error: self.errors.append(error))

        def wait(self, condition):
            deadline = time.monotonic() + 4
            while not condition() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertTrue(condition())

        def tearDown(self):
            self.gate.set()
            self.wait(lambda: not self.canvas._workers)
            for record in reversed(self.runtime.snapshot()):
                if record['state'] == 'running':
                    self.runtime.stop_component(record['id'], persist=False)
            QTest.qWait(30)

        def queue_attach(self):
            self.client.call('canvas', 'mount', {'target': 'provider'}, context=self.context)
            self.wait(self.waiting.is_set)
            self.assertEqual(self.provider.created, 0)

        def test_canvas_stop_and_new_instance_cancel_waiting_attach(self):
            self.queue_attach()
            self.runtime.stop_component('canvas')
            self.runtime.start_component('canvas')
            replacement = self.runtime.component_instance('canvas')
            self.assertIsNot(replacement, self.canvas)
            self.client.call('canvas', 'show', context=self.context)
            self.gate.set()
            self.wait(lambda: not self.canvas._workers)
            self.assertEqual(self.provider.created, 0)
            self.assertEqual(replacement.status()['mounts'], [])
            self.assertEqual(self.errors, [])

        def test_stop_during_provider_create_discards_late_native_result(self):
            self.canvas.dispatcher.run = self.original_run
            self.gate.set()
            stopper_errors = []
            def stop():
                try:
                    self.runtime.stop_component('canvas')
                except Exception as error:
                    stopper_errors.append(error)
            def during_create():
                self.stopper = threading.Thread(target=stop)
                self.stopper.start()
                deadline = time.monotonic() + 2
                while self.canvas.running and time.monotonic() < deadline:
                    time.sleep(0.001)
                self.assertFalse(self.canvas.running)
            self.provider.on_create = during_create
            self.client.call('canvas', 'mount', {'target': 'provider'}, context=self.context)
            self.wait(lambda: self.provider.created == 1)
            self.wait(lambda: not self.canvas._workers and not self.stopper.is_alive())
            self.assertEqual(stopper_errors, [])
            self.assertEqual(self.canvas.status()['mounts'], [])
            import shiboken6
            self.wait(lambda: all(not shiboken6.isValid(item) for item in self.provider.items.values()))
            self.assertEqual(self.errors, [])

        def test_stopped_window_rejects_destroyed_parent_without_rebuilding(self):
            self.queue_attach()
            self.runtime.stop_component('window')
            self.gate.set()
            self.wait(lambda: not self.canvas._workers)
            self.assertEqual(self.provider.created, 0)
            self.assertEqual(self.canvas.status()['mounts'], [])
            self.assertEqual(self.errors, [])

        def test_window_replacement_cancels_destroyed_parent_attach(self):
            self.queue_attach()
            manifest = self.runtime.status('window')['manifest']
            self.runtime.replace_component('window', manifest, lambda: WindowHost(runtime=self.runtime))
            self.client.call('canvas', 'show', context=self.context)
            self.gate.set()
            self.wait(lambda: not self.canvas._workers)
            self.assertEqual(self.provider.created, 0)
            self.assertEqual(self.canvas.status()['mounts'], [])
            self.assertEqual(self.errors, [])

    unittest.main()
