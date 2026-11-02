"""Run Qt's process-global application in an isolated GUI test process."""
if __name__ == '__main__':
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import unittest
    from pathlib import Path
    try:
        from PySide6.QtGui import QGuiApplication
        from polaris_platform.desktop import WindowHost, Canvas, Pet, Manager
    except ImportError:
        QGuiApplication = None
    from polaris_platform.bootstrap import from_file
    from polaris_platform.component import Component
    from polaris_platform.protocol import PlatformError


    @unittest.skipUnless(QGuiApplication, 'Optional PySide6 is not installed')
    class DesktopTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.runtime = from_file(Path(__file__).parents[1] / 'config.headless.json')
            self.host = WindowHost(runtime=self.runtime)
            self.canvas = Canvas(runtime=self.runtime)
            self.pet = Pet(runtime=self.runtime)
            self.manager = Manager(self.runtime)
            for identity, component in [('window', self.host), ('canvas', self.canvas), ('pet', self.pet), ('manager', self.manager), ('user', Component())]:
                self.runtime.install({'id': identity, 'name': identity, 'version': '1', 'platformApi': 1, 'entry': {'mode': 'inprocess'}}, lambda component=component: component)
                self.runtime.start_component(identity)
            for target in ['window', 'canvas', 'pet']:
                for operation in self.runtime.status(target)['description']['operations']:
                    self.runtime.grant('user', target, operation)
            self.context = self.runtime.user_context('user')

        def tearDown(self):
            for identity in ['manager', 'pet', 'canvas', 'window']:
                self.runtime.stop_component(identity)
            self.app.processEvents()

        def call(self, target, operation, params=None):
            return self.runtime.client('user').call(target, operation, params or {}, context=self.context)

        def test_pet_dependency_availability_does_not_change_grants(self):
            grants = self.runtime.authorization.decisions()
            def operations():
                return self.runtime.collaboration.describe_target('pet')['description']['operations']
            self.assertTrue(operations()['open_canvas'].get('available', True))
            self.runtime.stop_component('canvas')
            self.assertFalse(operations()['open_canvas'].get('available', True))
            self.assertTrue(operations()['say'].get('available', True))
            self.assertTrue(operations()['show'].get('available', True))
            self.runtime.start_component('canvas')
            self.assertTrue(operations()['open_canvas'].get('available', True))
            self.runtime.stop_component('window')
            self.assertFalse(operations()['open_canvas'].get('available', True))
            self.assertTrue(operations()['status'].get('available', True))
            self.runtime.start_component('window')
            self.assertTrue(operations()['open_canvas'].get('available', True))
            self.assertEqual(self.runtime.authorization.decisions(), grants)

        def test_canvas_contract_group_pins_the_session_and_permission_preview(self):
            rt = self.runtime
            self.call('pet', 'show')
            self.canvas.withdraw_event('dismissed')
            with self.assertRaises(PlatformError) as caught:
                self.pet.open_canvas(self.context)
            self.assertEqual(caught.exception.details['contract'], 'polaris.canvas.dismissed@1')
            self.assertTrue(self.pet.status()['visible'])
            self.assertFalse(self.canvas.status()['visible'])
            self.canvas.event('dismissed', provides='polaris.canvas.dismissed@1')

            alternate = Component()
            seen, state = [], {}
            def show(params, ctx):
                state.update(visible=True, sessionId=params['sessionId'])
                seen.append('show')
                return dict(state)
            alternate.operation('present', 'write', provides='polaris.canvas.show@1')(show)
            alternate.operation('inspect', provides='polaris.canvas.status@1')(lambda p, c: seen.append('status') or dict(state))
            alternate.event('closed', provides='polaris.canvas.dismissed@1')
            rt.install(dict(id='alternate', name='Alternate', version='1', platformApi=1, entry={'mode':'inprocess'}), lambda: alternate)
            rt.start_component('alternate')
            def choose(target):
                rt.select_provider('pet', 'operation', 'open_canvas', 'show', rt.status(target)['installation'], rt.status('pet')['installation'])
            try:
                from PySide6.QtCore import Qt
                from PySide6.QtTest import QTest
                self.manager.show()
                self.wait_bridge()
                self.manager.bridge.refresh()
                self.wait_bridge()
                window = self.manager._view
                root = window.rootObject()
                root.setProperty('selectedId', 'pet')
                def click(name):
                    controls = []
                    items = [root]
                    while items:
                        item = items.pop()
                        if item.objectName().startswith(('dependencies_', 'provider_')):
                            controls.append(item.objectName())
                        if item.objectName() == name:
                            pos = item.mapToScene(item.boundingRect().center()).toPoint()
                            self.assertTrue(item.isVisible() and item.isEnabled(), (name, pos))
                            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)
                            QTest.qWait(25)
                            self.wait_bridge()
                            return
                        items.extend(item.childItems())
                    self.fail(f"Missing {name}, open={root.property('expandedCapability')}, controls={controls}")
                click('dependencies_open_canvas')
                click('provider_canvas_alternate')
                preview = self.manager.bridge._make_plan('user', 'pet', 'open_canvas')
                self.assertEqual({row['name'] for row in preview['permissions'] if row['target'] == 'alternate'},
                                 {'present', 'inspect', 'closed'})
                self.assertFalse(any(row['target'] == 'canvas' for row in preview['permissions']))
                for name, kind in [('present', 'operation'), ('inspect', 'operation'), ('closed', 'event')]:
                    rt.grant('user', 'alternate', name, kind)
                rt.grant('user', 'canvas', 'dismissed', 'event')
                self.context = rt.user_context('user')
                self.call('pet', 'open_canvas')
                old_id = self.pet.status()['activeSession']
                choose('canvas')
                self.pet.monitor_session()
                self.assertEqual(seen, ['show', 'status'])
                alternate.port.publish('closed', {'sessionId': old_id}, self.context)
                self.assertTrue(self.pet.status()['visible'])
                self.call('pet', 'open_canvas')
                alternate.port.publish('closed', {'sessionId': old_id}, self.context)
                self.assertTrue(self.canvas.status()['visible'])
                self.assertNotEqual(self.pet.status()['activeSession'], old_id)
                self.call('canvas', 'hide')
            finally:
                rt.stop_component('alternate')

        def test_management_control_is_optional_and_about_uses_metadata(self):
            import json
            from unittest.mock import patch
            from PySide6.QtCore import QObject
            from polaris_platform.desktop.management_control import ManagementControlPort
            from polaris_platform import metadata
            control = ManagementControlPort(self.runtime)
            control.report_notice('local notice')
            self.assertEqual(self.manager.bridge.notice, 'local notice')
            self.manager.show()
            root = self.manager._view.rootObject()
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            button = root.findChild(QObject, 'aboutButton')
            point = button.mapToScene(button.boundingRect().center()).toPoint()
            QTest.mouseClick(self.manager._view, Qt.LeftButton, Qt.NoModifier, point)
            self.app.processEvents()
            self.assertTrue(root.findChild(QObject, 'aboutDialog').property('visible'))
            info = json.loads(self.manager.bridge.aboutJson)
            self.assertEqual(info['DISPLAY_VERSION'], metadata.DISPLAY_VERSION)
            class AlternateManager(Component):
                def __init__(self):
                    super().__init__()
                    self.visible = False
                    self.operation('show')(self.display)
                    self.operation('status')(lambda p, c: {'visible': self.visible})
                    self.operation('hide')(lambda p, c: setattr(self, 'visible', False))
                def display(self, p, c):
                    self.visible = True
                    return {'visible': True}
            manifest = self.runtime.status('manager')['manifest']
            self.runtime.replace_component('manager', manifest, AlternateManager)
            self.assertTrue(control.show()['visible'])
            control.refresh()
            with patch('sys.stderr') as stderr:
                control.report_notice('startup failed')
                self.assertTrue(stderr.write.called)
            with self.assertRaises(PlatformError) as error:
                control.request_mount('canvas', 'example', 'main')
            self.assertEqual(error.exception.code, 'management_unavailable')

        def test_window_creation_profiles_and_dynamic_input_regions(self):
            import tempfile
            from PySide6.QtCore import QPoint, QRect
            from PySide6.QtGui import QRegion
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / 'Region.qml'
                source.write_text("import QtQuick\nRectangle { color: 'transparent'; property bool followRight: false; property var manualRegions: [{x:20,y:20,width:60,height:60,radius:30}]; property var regions: followRight ? [{x:width-10,y:0,width:10,height:10}] : manualRegions }", encoding='utf8')
                ordinary = self.call('window','create',{'source':str(source),'size':[100,100]})['handle']
                state = self.call('window','status',{'handle':ordinary})
                self.assertFalse(state['toolWindow'])
                self.assertTrue(state['acceptFocus'])
                self.assertFalse(state['inputRegionConfigured'])
                self.assertTrue(self.host._views[ordinary].mask().isEmpty())
                masked = self.call('window','create',{'source':str(source),'size':[100,100],
                    'options':{'toolWindow':True,'acceptFocus':False,'inputRegionsProperty':'regions'}})['handle']
                view = self.host._views[masked]
                state = self.call('window','status',{'handle':masked})
                self.assertTrue(state['toolWindow'])
                self.assertFalse(state['acceptFocus'])
                self.assertTrue(view.mask().contains(QPoint(50,50)))
                self.assertFalse(view.mask().contains(QPoint(20,20)))
                self.call('window','update',{'handle':masked,'properties':{'manualRegions':[]}})
                self.assertFalse(view.mask().isEmpty(), 'empty input must not reset to a full window')
                self.assertTrue(view.mask().intersected(QRegion(QRect(0,0,100,100))).isEmpty())
                self.call('window','update',{'handle':masked,'properties':{'manualRegions':[{'x':0,'y':0,'width':10,'height':10}]}})
                self.assertTrue(view.mask().contains(QPoint(5,5)))
                self.assertFalse(view.mask().contains(QPoint(50,50)))
                self.call('window','update',{'handle':masked,'properties':{'followRight':True}})
                view.resize(120,100)
                self.app.processEvents()
                self.assertTrue(view.mask().contains(QPoint(115,5)))
                self.assertFalse(view.mask().contains(QPoint(95,5)))
                self.call('window','update',{'handle':masked,'properties':{'manualRegions':'bad','followRight':False}})
                self.assertTrue(self.call('window','status',{'handle':masked})['inputRegionError'])
                self.assertTrue(view.mask().intersected(QRegion(QRect(0,0,120,100))).isEmpty())
                self.call('window','update',{'handle':masked,'properties':{'manualRegions':[{'x':0,'y':0,'width':10,'height':10}]}})
                self.assertEqual(self.call('window','status',{'handle':masked})['inputRegionError'],'')
                self.call('window','hide',{'handle':masked})
                self.call('window','show',{'handle':masked})
                self.assertTrue(self.call('window','status',{'handle':masked})['toolWindow'])
                count = len(self.host._views)
                with self.assertRaises(PlatformError):
                    self.call('window','create',{'source':str(source),'options':{'inputRegionsProperty':'missing'}})
                self.assertEqual(len(self.host._views),count)
                with self.assertRaises(PlatformError):
                    self.call('window','create',{'source':str(source),'properties':{'manualRegions':'invalid'},
                        'options':{'inputRegionsProperty':'regions'}})
                self.assertEqual(len(self.host._views),count)
                self.call('window','release',{'handle':masked})
                self.assertNotIn(masked,self.host._views)

        def test_real_windows_hide_stop_and_recovery(self):
            self.call('canvas', 'set_cards', {'cards': [{'title': 'Hello', 'text': 'A card'}]})
            self.assertTrue(self.call('canvas', 'show')['visible'])
            self.assertFalse(self.call('canvas', 'hide')['visible'])
            self.assertEqual(self.runtime.status('canvas')['state'], 'running')
            self.assertEqual(self.canvas.cards[0]['title'], 'Hello')
            self.call('pet', 'say', {'message': 'Hello'})
            self.manager.show()
            self.runtime.stop_component('canvas')
            self.assertTrue(self.manager.status()['visible'])
            self.runtime.stop_component('window')
            self.assertTrue(self.manager.status()['visible'])
            with self.assertRaises(PlatformError): self.call('pet', 'show')
            self.runtime.stop_component('pet')
            self.assertEqual(self.runtime.status('pet')['state'], 'stopped')
            self.assertTrue(self.manager.status()['visible'])
            self.runtime.start_component('window')
            self.runtime.start_component('pet')
            self.assertTrue(self.call('pet', 'show')['visible'])
            self.manager.show()
            self.assertTrue(self.manager.status()['visible'])

        def test_gui_assets_and_snapshot(self):
            self.call('canvas', 'show')
            self.call('pet', 'show')
            self.manager.show()
            for _ in range(30): self.app.processEvents()
            for view in list(self.host._views.values()) + [self.manager._view]:
                self.assertFalse(view.errors())
                image = view.grabWindow()
                self.assertFalse(image.isNull())
            self.assertIn('canvas', [item['id'] for item in self.runtime.snapshot()])

        def test_distinct_window_provider_replacement(self):
            self.call('canvas', 'show')
            self.call('pet', 'say', {'message': 'Keep this bubble'})
            old_handle = self.canvas.handle
            class AlternateWindow(WindowHost):
                pass
            manifest = self.runtime.status('window')['manifest']
            self.runtime.replace_component('window', manifest, lambda: AlternateWindow(runtime=self.runtime))
            replacement = self.runtime.component_instance('window')
            self.assertIsNot(replacement, self.host)
            self.assertTrue(self.call('canvas', 'show')['visible'])
            self.assertNotEqual(self.canvas.handle, old_handle)
            self.assertTrue(self.call('pet', 'show')['visible'])
            self.assertEqual(self.pet.properties['message'], 'Keep this bubble')
            self.manager.show()
            self.assertTrue(self.manager.status()['visible'])
            self.runtime.stop_component('canvas')
            self.assertEqual(len(replacement._views), 1)

        def wait_bridge(self):
            import time
            deadline = time.monotonic() + 5
            while self.manager.bridge.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertFalse(self.manager.bridge.busy)

        def test_explicit_view_plan_and_dynamic_event_permissions(self):
            import json
            self.wait_bridge()
            bridge = self.manager.bridge
            bridge.prepareView('manager', 'canvas', 'show')
            self.wait_bridge()
            plan = json.loads(bridge.planJson)
            self.assertEqual({(row['target'], row['name']) for row in plan},
                             {('canvas', 'show'), ('window', 'status'), ('window', 'create'), ('window', 'show')})
            self.assertTrue(all(not row['authorized'] for row in plan))
            self.assertFalse(self.runtime.authorization.scope('manager'))
            bridge.confirmView()
            self.wait_bridge()
            self.assertTrue(self.canvas.status()['visible'])
            self.assertEqual(len(self.runtime.authorization.scope('manager')), 4)
            self.canvas.events['changed'] = {'access': 'read', 'major': 1, 'revision': 1}
            self.canvas.port.advertise()
            bridge.refresh()
            self.wait_bridge()
            records = json.loads(bridge.dataJson)
            self.assertIn('changed', next(row for row in records if row['id'] == 'canvas')['description']['events'])
            bridge.permission('manager', 'canvas', 'changed', 'event', True, True)
            self.wait_bridge()
            self.assertEqual(len(self.runtime.authorization.scope('manager', True)), 1)
            self.assertEqual(len(self.runtime.authorization.scope('manager')), 4)
            bridge.permission('manager', 'canvas', 'changed', 'event', True, False)
            self.wait_bridge()
            self.assertFalse(self.runtime.authorization.scope('manager', True))

        def test_card_plain_text_and_long_pet_bubble_are_contained(self):
            self.call('canvas', 'set_cards', {'cards': [
                {'title': '<b>Plain title</b>', 'text': '<i>Plain body</i>'},
                {'title': 'Second card', 'text': 'Second body'}]})
            self.call('canvas', 'show')
            message = '<b>' + 'Long message ' * 150 + '</b>'
            self.call('pet', 'say', {'message': message})
            for _ in range(30): self.app.processEvents()
            canvas_root = self.host._views[self.canvas.handle].rootObject()
            def named_items(item, name):
                result = [item] if item.objectName() == name else []
                for child in item.childItems():
                    result.extend(named_items(child, name))
                return result
            titles = named_items(canvas_root, 'cardTitle')
            self.assertEqual(len(titles), 2)
            self.assertEqual(titles[0].property('text'), '<b>Plain title</b>')
            pet_root = self.host._views[self.pet.handle].rootObject()
            bubble = named_items(pet_root, 'bubbleScroll')[0]
            text = named_items(pet_root, 'petMessage')[0]
            self.assertTrue(bubble.property('clip'))
            self.assertGreater(text.property('height'), bubble.property('height'))
            self.assertEqual(text.property('text'), message)

        def test_nested_display_does_not_borrow_grants(self):
            # A canvas grant alone cannot acquire its window dependency permissions.
            self.runtime.install({'id':'restricted', 'name':'restricted', 'version':'1', 'platformApi':1, 'entry':{'mode':'inprocess'}}, Component)
            self.runtime.start_component('restricted')
            self.runtime.grant('restricted', 'canvas', 'show')
            context = self.runtime.user_context('restricted')
            with self.assertRaises(PlatformError):
                self.runtime.client('restricted').call('canvas', 'show', {}, context=context)
    unittest.main()
else:
    import os
    import subprocess
    import sys
    import unittest
    from pathlib import Path

    class DesktopProcessTests(unittest.TestCase):
        def test_offscreen_desktop_lifecycle_permissions_and_rendering(self):
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        def test_two_gui_processes_restore_identity_and_display_grants(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            import json
            import tempfile
            script = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from polaris_platform.bootstrap import from_file
from polaris_platform.desktop import run
app = QGuiApplication([])
runtime = from_file(Path(sys.argv[1]), state_dir=sys.argv[2])
phase = sys.argv[3]
result = {}
def exercise():
    try:
        manager = runtime.component_instance('manager')
        if phase == 'first':
            plugin = Path(sys.argv[2]) / 'sdk-plugin'
            plugin.mkdir()
            (plugin / 'manifest.json').write_text(json.dumps({'id': 'sdk-probe', 'name': 'SDK probe', 'version': '1', 'platformApi': 1, 'entry': {'mode': 'inprocess', 'factory': 'sdk_probe:create'}}))
            (plugin / 'sdk_probe.py').write_text('from polaris_platform.sdk import Component\ndef create():\n c=Component()\n @c.operation("echo")\n def echo(value): return value\n return c\n')
            runtime.install_directory(plugin)
            runtime.start_component('sdk-probe')
            runtime.grant('sdk-probe', 'sdk-probe', 'echo')
        result['sdkEcho'] = runtime.client('sdk-probe').call('sdk-probe', 'echo', {'value': 'ready'}, context=runtime.user_context('sdk-probe'))
        if phase == 'first':
            plan = manager.bridge._make_plan('manager', 'canvas', 'show')
            for row in plan['permissions']:
                runtime.grant('manager', row['target'], row['name'])
        result['display'] = runtime.client('manager').call('canvas', 'show', {}, context=runtime.user_context('manager'))
        result['identity'] = {row['id']: row['installation'] for row in runtime.snapshot()}
        result['grants'] = len(runtime.authorization.scope('manager'))
        result['managerVisible'] = manager.status()['visible']
    except Exception as exc:
        result['error'] = repr(exc)
    finally:
        QTimer.singleShot(30, app.quit)
QTimer.singleShot(60, exercise)
runtime.manager_config['defaultSources'] = []
result['exit'] = run(runtime)
print(json.dumps(result))
'''
            config = Path(__file__).resolve().parents[1] / 'config.headless.json'
            results = []
            with tempfile.TemporaryDirectory() as directory:
                for phase in ['first', 'second']:
                    result = subprocess.run([sys.executable, '-c', script, str(config), directory, phase],
                                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertNotIn('error', payload)
                    self.assertTrue(payload['display']['visible'])
                    self.assertFalse(payload['managerVisible'])
                    self.assertEqual(payload['sdkEcho'], 'ready')
                    self.assertEqual(payload['grants'], 4)
                    results.append(payload)
            self.assertEqual(results[0]['identity'], results[1]['identity'])
