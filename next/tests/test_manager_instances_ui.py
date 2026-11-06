"""Generic instance creation through real Manager QML and Canvas native views."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

if __name__ != '__main__':
    class ManagerInstancesUIProcessTests(unittest.TestCase):
        def test_create_stop_start_and_mount_independent_instance(self):
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import json
    import shutil
    import tempfile
    import time
    from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, Qt
    from PySide6.QtGui import QGuiApplication
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.desktop import Canvas, WindowHost, Manager

    def find(item, name):
        if item.objectName() == name: return item
        for child in item.childItems():
            result = find(child, name)
            if result is not None: return result

    class ManagerInstancesTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls): cls.qt = QGuiApplication([])
        def wait(self, predicate):
            end = time.monotonic() + 7
            while not predicate() and time.monotonic() < end:
                self.qt.processEvents()
                time.sleep(.005)
            self.assertTrue(predicate(), self.manager.bridge.notice)
        def click(self, name):
            self.qt.processEvents()
            button = find(self.manager._view.contentItem(), name)
            self.assertIsNotNone(button, name)
            self.assertTrue(button.isVisible(), name)
            self.assertTrue(button.property('enabled'), name)
            self.assertTrue(QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection))
            self.wait(lambda: not self.manager.bridge.busy)
            self.qt.processEvents()
        def test_generic_instance_lifecycle_and_canvas_mount(self):
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                source = directory / 'counter'
                shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/counter', source)
                manifest = json.loads((source / 'manifest.json').read_text())
                manifest['instances'] = {'mode': 'multiple'}
                (source / 'manifest.json').write_text(json.dumps(manifest))
                module = source / 'counter_plugin.py'
                module.write_text(module.read_text().replace('def create():', 'def create(instance_context=None):'))
                self.runtime = build(default_config(), state_dir=directory / 'runtime')
                window_host = WindowHost(runtime=self.runtime)
                canvas = Canvas(runtime=self.runtime, collapse_delay=100000)
                self.manager = Manager(self.runtime)
                try:
                    for identity, component in [('window', window_host), ('canvas', canvas), ('manager', self.manager), ('user', Component())]:
                        self.runtime.install(dict(id=identity, name=identity, version='1', platformApi=1,
                            entry={'mode': 'inprocess'}), lambda c=component: c)
                        self.runtime.start_component(identity)
                    self.runtime.install_directory(source)
                    self.runtime.start_component('org.example.counter')
                    self.manager.show()
                    self.wait(lambda: not self.manager.bridge.busy)
                    self.manager.bridge.refresh()
                    self.wait(lambda: not self.manager.bridge.busy)
                    root = self.manager._view.rootObject()
                    root.setProperty('selectedId', 'org.example.counter')
                    self.click('createComponentInstance')
                    first = root.property('selectedId')
                    self.assertNotEqual(first, 'org.example.counter')
                    self.assertEqual(self.runtime.status(first)['state'], 'running')
                    self.assertEqual(self.runtime._records[first]['config'], {})
                    records = json.loads(self.manager.bridge.dataJson)
                    first_row = next(row for row in records if row['id'] == first)
                    self.assertIn(first[:8], first_row['name'])
                    uninstall = find(self.manager._view.contentItem(), 'uninstallComponent')
                    self.assertFalse(uninstall.property('enabled'))
                    self.manager.bridge.prepareUninstall(first)
                    self.wait(lambda: not self.manager.bridge.busy)
                    self.assertIsNone(self.manager.bridge._installation_plan)
                    self.assertIn('org.example.counter', [row['manifest']['id'] for row in self.runtime.export_installations()])
                    self.click('createComponentInstance')
                    second = root.property('selectedId')
                    self.assertNotEqual(first, second)
                    self.assertNotEqual(self.runtime.component_data_directory(first), self.runtime.component_data_directory(second))
                    self.click('stopComponentInstance')
                    self.assertEqual(self.runtime.status(second)['state'], 'stopped')
                    self.assertEqual(self.runtime.status(first)['state'], 'running')
                    self.click('startComponentInstance')
                    self.assertEqual(self.runtime.status(second)['state'], 'running')
                    self.assertEqual(self.runtime.status('org.example.counter')['state'], 'running')
                    for target in ('window', 'canvas'):
                        for operation in self.runtime.status(target)['description']['operations']:
                            self.runtime.grant('user', target, operation)
                    self.runtime.client('user').call('canvas', 'show', context=self.runtime.user_context('user'))
                    canvas.actions.refreshViews()
                    choices = json.loads(canvas.actions.viewsJson)
                    self.assertIn(first, [row['target'] for row in choices])
                    self.assertIn(second, [row['target'] for row in choices])
                    first_choice = next(row for row in choices if row['target'] == first)
                    second_choice = next(row for row in choices if row['target'] == second)
                    self.assertNotEqual(first_choice['componentName'], second_choice['componentName'])
                    self.assertIn(first[:8], first_choice['componentName'])
                    self.assertIn(second[:8], second_choice['componentName'])
                    default_choice = next(row for row in choices if row['target'] == self.runtime.status('org.example.counter')['instanceId'])
                    self.assertIn('默认实例', default_choice['componentName'])
                    index = next(index for index, row in enumerate(choices) if row['target'] == second)
                    canvas.actions.mountSelected(index)
                    self.wait(lambda: not self.manager.bridge.busy and self.manager.bridge._pending_plan is not None)
                    self.click('confirmPermission')
                    self.wait(lambda: any(row['state'] == 'mounted' and row['target'] == second for row in canvas.status()['mounts']))
                    mounted = next(row for row in canvas.status()['mounts'] if row['target'] == second)
                    self.assertIn(second[:8], mounted['title'])
                    self.assertFalse(self.runtime.authorization.scope(first), 'Creating another instance must not transfer authority')
                    self.assertEqual(self.runtime.component_instance(first).value(), 0)
                    self.assertEqual(self.runtime.component_instance(second).value(), 0)
                    root.setProperty('selectedId', first)
                    self.click('stopComponentInstance')
                    self.click('deleteComponentInstance')
                    self.assertIn('删除实例', self.manager.bridge.installationPrompt)
                    self.click('cancelInstallation')
                    self.assertEqual(self.runtime.status(first)['state'], 'stopped')
                    self.click('deleteComponentInstance')
                    from polaris_platform.application import ApplicationDefinition
                    dependent = ApplicationDefinition('引用保护测试')
                    self.runtime.ensure_application(dependent)
                    self.runtime.register_application_bindings(dependent.id, [first])
                    self.click('confirmInstallation')
                    self.assertIn(first, [row['id'] for row in self.runtime.snapshot()])
                    self.assertIn('引用', self.manager.bridge.notice)
                    self.runtime.unregister_application_principal(dependent.id)
                    self.click('deleteComponentInstance')
                    self.click('confirmInstallation')
                    self.assertNotIn(first, [row['id'] for row in self.runtime.snapshot()])
                    self.assertEqual(self.runtime.status(second)['state'], 'running')
                    self.assertEqual(self.runtime.status('org.example.counter')['state'], 'running')
                    root.setProperty('selectedId', 'user')
                    self.qt.processEvents()
                    self.assertFalse(find(self.manager._view.contentItem(), 'createComponentInstance').isVisible())
                    failed_default = []
                    def fail_additional(instance_context):
                        if instance_context['instanceId'] != failed_default[0]:
                            raise RuntimeError('测试实例启动失败')
                        return Component()
                    self.runtime.install(dict(id='fails-extra', name='启动失败示例', version='1', platformApi=1,
                        entry={'mode': 'inprocess'}, instances={'mode': 'multiple'}), fail_additional)
                    failed_default.append(self.runtime.status('fails-extra')['instanceId'])
                    self.runtime.start_component('fails-extra')
                    self.manager.bridge.refresh()
                    self.wait(lambda: not self.manager.bridge.busy)
                    root.setProperty('selectedId', 'fails-extra')
                    self.click('createComponentInstance')
                    failed_id = root.property('selectedId')
                    self.assertNotEqual(failed_id, 'fails-extra')
                    self.assertEqual(self.runtime.status(failed_id)['state'], 'failed')
                    self.assertIn('启动失败', self.manager.bridge.notice)
                    self.assertFalse(find(self.manager._view.contentItem(), 'uninstallComponent').property('enabled'))
                    self.click('deleteComponentInstance')
                    self.click('confirmInstallation')
                    self.assertNotIn(failed_id, [row['id'] for row in self.runtime.snapshot()])
                    root.setProperty('selectedId', second)
                    capture = os.environ.get('POLARIS_FEISHU_CAPTURE')
                    if capture:
                        Path(capture).mkdir(parents=True, exist_ok=True)
                        self.manager._view.grabWindow().save(str(Path(capture) / 'manager-instances.png'))
                finally:
                    for row in reversed(self.runtime.snapshot()):
                        if row['state'] == 'running': self.runtime.stop_component(row['id'], force=True, persist=False)
                    for _ in range(5):
                        self.qt.processEvents()
                        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    unittest.main()
