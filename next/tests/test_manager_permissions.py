import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class ComponentPermissionTests(unittest.TestCase):
    def test_presets_are_exact_and_do_not_change_background_access(self):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtTest import QTest
        from polaris_platform.bootstrap import build, default_config
        from polaris_platform.component import Component
        from polaris_platform.desktop.manager import ManagerBridge
        app = QGuiApplication.instance() or QGuiApplication([])
        runtime = build(default_config())
        target = Component()
        target.operation('read')(lambda p, c: {})
        target.operation('write', access='write')(lambda p, c: {})
        for name, component in [('user', Component()), ('example', target)]:
            runtime.install(dict(id=name, name=name, version='1', platformApi=1, entry=dict(mode='inprocess')), lambda c=component: c)
            runtime.start_component(name)
        bridge = ManagerBridge(runtime)
        runtime.grant('user', 'example', 'read', background=True)
        background = runtime.authorization.scope('user', True)
        def choose(mode):
            bridge.componentPermission('user', 'example', mode)
            for _ in range(300):
                app.processEvents()
                if not bridge.busy: break
                QTest.qWait(5)
            self.assertFalse(bridge.busy)
            return {key[2] for key in runtime.authorization.scope('user')}
        try:
            self.assertEqual(choose('all'), {'read', 'write'})
            target.operation('later')(lambda p, c: {})
            target.port.advertise()
            self.assertEqual({key[2] for key in runtime.authorization.scope('user')}, {'read', 'write'})
            self.assertEqual(choose('read'), {'read', 'later'})
            self.assertEqual(choose('none'), set())
            self.assertEqual(runtime.authorization.scope('user', True), background)
        finally:
            bridge._closed = True
            for row in reversed(runtime.snapshot()):
                if row['state'] == 'running': runtime.stop_component(row['id'], persist=False)
