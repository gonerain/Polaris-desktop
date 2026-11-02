"""Native settings grants belong to the provider, never its display host."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

class NativeInputProcessTests(unittest.TestCase):
    def test_native_input_boundary(self):
        if importlib.util.find_spec('PySide6') is None:
            self.skipTest('Qt unavailable')
        result = subprocess.run([sys.executable, __file__, 'qt'], env=dict(os.environ,
            QT_QPA_PLATFORM='offscreen'), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__' and sys.argv[-1] == 'qt':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import threading
    from unittest.mock import patch
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow, QQuickItem
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.sdk import Component
    from polaris_platform.protocol import PlatformError
    class Provider(Component):
        def __init__(self):
            super().__init__()
            self.operation('create_view', access='write')(self.create)
            self.operation('release_view', access='write')(self.release)
            self.operation('configure', access='write')(self.configure)
            self.operation('ordinary')(self.ordinary)
            self.views = [dict(id='main',adapter='qt-quick-item',create='create_view',release='release_view')]
        def describe(self):
            result = super().describe()
            for name in ('create_view','release_view'):
                result['operations'][name]['profile'] = 'qt-native'
            return result
        def create(self, parent, view, ctx):
            self.input = ctx.local_view_input(parent)
            self.item = QQuickItem(parent)
            self.input.bind(self.item)
            return {}
        def release(self, parent, ctx):
            return ctx.local_view_input(parent)
        def configure(self, ctx):
            ctx.require_permissions([('target','read')])
            ctx.remember_task('test', [('target','read')])
            return ctx.context.origin
        def ordinary(self, ctx, parent=None):
            if parent is not None:
                return ctx.local_view_input(parent)
            return self.input.call('configure', {}, permissions=[('target','read')])
    class NativeBoundaryTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls): cls.app = QGuiApplication([])
        def setUp(self):
            self.runtime = build(default_config())
            target = Component(); target.operation('read')(lambda: {'ok':True})
            for identity,factory in [('host',Component),('provider',Provider),('target',lambda:target)]:
                self.runtime.install(dict(id=identity,name=identity,version='1',platformApi=1,entry=dict(mode='inprocess')),factory)
                self.runtime.start_component(identity)
            self.provider = self.runtime.component_instance('provider')
            for name in ('create_view','ordinary','release_view'):
                self.runtime.grant('host','provider',name)
            self.window = QQuickWindow(); self.window.resize(200,100); self.window.show()
            self.call('create_view',dict(parent=self.window.contentItem(),view='main'))
            self.port = self.provider.input
        def call(self,operation,params=None):
            return self.runtime.client('host').call('provider',operation,params,context=self.runtime.user_context('host'))
        def save(self):
            return self.port.call('configure',{},permissions=[('provider','configure'),('target','read')])
        def tearDown(self):
            self.window.close()
            for row in reversed(self.runtime.snapshot()):
                if row['state']=='running': self.runtime.stop_component(row['id'])
        def test_provider_origin_and_no_host_grants(self):
            self.assertEqual(self.save(),'provider')
            handle = self.runtime.client('provider').bind('target','read')
            self.assertIn(handle.semantic,self.runtime.authorization.scope('provider'))
            self.assertNotIn(handle.semantic,self.runtime.authorization.scope('host'))
            task = next(iter(self.runtime._tasks.values()))
            self.assertEqual(task['origin'],'provider')
            self.runtime.revoke('provider','target','read')
            with self.assertRaises(PlatformError): self.runtime.client('provider').call('target','read',context=self.runtime.user_context('provider'))
        def test_ordinary_handlers_cannot_mint_or_use_input(self):
            with self.assertRaises(PlatformError): self.call('ordinary',dict(parent=self.window.contentItem()))
            with self.assertRaises(PlatformError): self.call('ordinary')
            with self.assertRaises(PlatformError) as denied:
                self.call('release_view',dict(parent=self.window.contentItem()))
            self.assertEqual(denied.exception.code,'permission_denied')
            errors=[]
            worker=threading.Thread(target=lambda: self.capture(errors,self.save));worker.start();worker.join()
            self.assertEqual(errors[0].code,'input_thread')
            self.assertFalse(self.runtime.authorization.scope('provider'))
        @staticmethod
        def capture(errors,function):
            try: function()
            except Exception as error: errors.append(error)
        def test_ordinary_configure_cannot_create_grants(self):
            self.runtime.grant('host','provider','configure')
            with self.assertRaises(PlatformError): self.call('configure')
            self.assertFalse(self.runtime.authorization.scope('provider'))
            self.assertFalse(self.runtime._tasks)
        def test_stale_hidden_and_released_inputs(self):
            self.window.hide()
            with self.assertRaises(PlatformError): self.save()
            self.window.show()
            self.provider.item.setVisible(False)
            with self.assertRaises(PlatformError): self.save()
            self.provider.item.setVisible(True)
            self.port.close()
            with self.assertRaises(PlatformError): self.save()
        def test_replaced_instance_cannot_authorize(self):
            self.runtime.stop_component('provider');self.runtime.start_component('provider')
            with self.assertRaises(PlatformError): self.save()
        def test_failed_task_save_rolls_back_grants(self):
            with patch.object(self.runtime,'_persist_tasks',side_effect=OSError('disk full')):
                with self.assertRaises(PlatformError): self.save()
            self.assertFalse(self.runtime.authorization.scope('provider'))
            self.assertFalse(self.runtime._tasks)
        def test_partial_grant_failure_rolls_back(self):
            original=self.runtime.authorization._persist
            count=[0]
            def once():
                count[0]+=1
                if count[0]==2: raise OSError('disk full')
                return original()
            with patch.object(self.runtime.authorization,'_persist',side_effect=once):
                with self.assertRaises(OSError): self.save()
            self.assertFalse(self.runtime.authorization.scope('provider'))
    unittest.main(argv=[sys.argv[0]], defaultTest='NativeBoundaryTests')
