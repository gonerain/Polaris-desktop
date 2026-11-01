"""Pet input sessions are exercised with real Qt mouse events in isolation."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

if __name__ != '__main__':
    class PetUIProcessTests(unittest.TestCase):
        def test_pointer_sessions_recovery_and_revocation(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                         env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                         capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        def test_pet_position_survives_two_independent_gui_hosts(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            import json
            import tempfile
            script = r'''import json,sys,time
from PySide6.QtCore import QObject,QPoint,QPointF,Qt,QTimer
from PySide6.QtGui import QGuiApplication, QCursor
from PySide6.QtTest import QTest
def _mouseMove(window,point):
 QCursor.setPos(window.mapToGlobal(point)); QTest.mouseMove(window,point)
def _mousePress(window,button,modifiers,point):
 QCursor.setPos(window.mapToGlobal(point)); QTest.mousePress(window,button,modifiers,point)
def _mouseRelease(window,button,modifiers,point):
 QCursor.setPos(window.mapToGlobal(point)); QTest.mouseRelease(window,button,modifiers,point)
from polaris_platform.bootstrap import build,default_config
from polaris_platform.desktop import run
app=QGuiApplication([])
runtime=build(default_config(),state_dir=sys.argv[1])
result={}
def wait(predicate):
 deadline=time.monotonic()+4
 while not predicate() and time.monotonic()<deadline:
  app.processEvents(); time.sleep(.01)
 assert predicate()
def find(item,name):
 if item.objectName()==name: return item
 for child in item.childItems():
  match=find(child,name)
  if match is not None: return match
def exercise():
 try:
  pet=runtime.component_instance('pet'); host=runtime.component_instance('window')
  manager=runtime.component_instance('manager')
  assert not manager.status()['visible']
  wait(lambda: bool(pet.handle) and host.view_status(pet.handle).get('visible'))
  if sys.argv[2]=='first':
   window=host._views[pet.handle]; hit=find(window.rootObject(),'petHitArea')
   point=hit.mapToScene(QPointF(hit.width()/2,hit.height()/2)); start=QPoint(round(point.x()),round(point.y()))
   _mousePress(window,Qt.LeftButton,Qt.NoModifier,start)
   for distance in (20,40,65):
    _mouseMove(window,start-QPoint(distance,20)); app.processEvents(); time.sleep(.03)
   _mouseRelease(window,Qt.LeftButton,Qt.NoModifier,start-QPoint(65,20))
   wait(lambda: pet._data_path.exists() and tuple(json.loads(pet._data_path.read_text())[k] for k in ('x','y'))==pet.position)
  native=host.view_status(pet.handle)
  result.update(position=[native['x'],native['y']],installation=runtime.status('pet')['installation'],visible=native['visible'])
  if sys.argv[2]=='second':
   window=host._views[pet.handle]; hit=find(window.rootObject(),'petHitArea')
   point=hit.mapToScene(QPointF(hit.width()/2,hit.height()/2)); point=QPoint(round(point.x()),round(point.y()))
   QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point)
   menu=window.rootObject().findChild(QObject,'petMenu')
   wait(lambda: menu.property('visible'))
   assert not manager.status()['visible']
   item=window.rootObject().findChild(QObject,'managePetMenuItem')
   point=item.mapToScene(QPointF(item.width()/2,item.height()/2))
   QTest.mouseClick(item.window(),Qt.LeftButton,Qt.NoModifier,QPoint(round(point.x()),round(point.y())))
   wait(lambda: manager.status()['visible'])
   runtime.revoke('pet','pet','show')
 except Exception as error: result['error']=repr(error)
 finally: app.quit()
def record_failure():
 pet=runtime.component_instance('pet'); host=runtime.component_instance('window')
 manager=runtime.component_instance('manager')
 result.update(visible=bool(pet and pet.handle and host.view_status(pet.handle).get('visible')),
               managerVisible=manager.status()['visible'],
               showGranted=any(key[0]==runtime.status('pet')['installation'] and key[2]=='show' for key in runtime.authorization.scope('pet')))
 if sys.argv[2]=='revoked': runtime.stop_component('pet')
if sys.argv[2] in ('revoked','disabled'): app.aboutToQuit.connect(record_failure)
else: QTimer.singleShot(40,exercise)
result['exit']=run(runtime)
print(json.dumps(result))
'''
            results = []
            with tempfile.TemporaryDirectory() as directory:
                for phase in ('first', 'second', 'revoked', 'disabled'):
                    process = subprocess.run([sys.executable, '-c', script, directory, phase],
                         env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                         capture_output=True, text=True, timeout=20)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    payload = json.loads(process.stdout)
                    self.assertNotIn('error', payload)
                    if phase in ('revoked', 'disabled'):
                        self.assertEqual(payload['exit'], 1)
                        self.assertIn('桌宠启动失败', process.stderr)
                        self.assertFalse(payload['visible'])
                        self.assertFalse(payload['managerVisible'])
                        self.assertFalse(payload['showGranted'], 'Startup must not restore a revoked initial pet permission')
                    else:
                        self.assertEqual(payload['exit'], 0)
                        self.assertTrue(payload['visible'])
                    results.append(payload)
            self.assertEqual(results[0]['installation'], results[1]['installation'])
            self.assertEqual(results[0]['position'], results[1]['position'])

else:
    import tempfile
    import time
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QCursor
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
    from polaris_platform.desktop import WindowHost, Canvas, Pet

    def find_item(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = find_item(child, name)
            if found is not None:
                return found
        return None

    class PetInteractionTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.directory = tempfile.TemporaryDirectory()
            self.runtime = build(default_config(), state_dir=self.directory.name)
            self.host = WindowHost(runtime=self.runtime)
            self.canvas = Canvas(runtime=self.runtime, collapse_delay=160)
            self.pet = Pet(runtime=self.runtime)
            for identity, component in [('window', self.host), ('canvas', self.canvas), ('pet', self.pet), ('user', Component())]:
                self.runtime.install({'id': identity, 'name': identity, 'version': '1', 'platformApi': 1,
                                      'entry': {'mode': 'inprocess'}}, lambda c=component: c)
                self.runtime.start_component(identity)
            for requester in ('user', 'pet'):
                for target in ('window', 'canvas', 'pet'):
                    for operation in self.runtime.status(target)['description']['operations']:
                        self.runtime.grant(requester, target, operation)
                self.runtime.grant(requester, 'canvas', 'dismissed', kind='event')
            self.context = self.runtime.user_context('user')
            self.call('pet', 'show')
            QTest.qWait(40)

        def tearDown(self):
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'], force=True)
            QTest.qWait(40)
            self.directory.cleanup()

        def wait(self, predicate, timeout=4):
            deadline = time.monotonic() + timeout
            while not predicate() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(predicate(), f'pet={self.pet.status()} notice={self.pet.bridge.notice} busy={self.pet.bridge.busy} canvas={self.canvas.status()} entered={self.canvas._entered} inside={self.canvas._inside} holds={self.canvas._holds}')

        def call(self, target, operation, params=None):
            return self.runtime.client('user').call(target, operation, params, context=self.context)

        def pet_visible(self):
            return bool(self.pet.handle and self.host.view_status(self.pet.handle).get('visible'))

        def canvas_visible(self):
            return bool(self.canvas.handle and self.host.view_status(self.canvas.handle).get('visible'))

        def pet_window(self):
            return self.host._views[self.pet.handle]

        def hit_point(self):
            hit = find_item(self.pet_window().rootObject(), 'petHitArea')
            point = hit.mapToScene(QPointF(hit.width()/2, hit.height()/2))
            return QPoint(round(point.x()), round(point.y()))

        def activate(self):
            _mouseClick(self.pet_window(), Qt.LeftButton, Qt.NoModifier, self.hit_point())
            self.wait(lambda: self.canvas_visible() and not self.pet_visible())

        def test_transparent_pet_click_canvas_leave_restores_pet(self):
            state = self.host.view_status(self.pet.handle)
            self.assertTrue(state['transparent'])
            self.assertTrue(state['frameless'])
            self.assertTrue(state['topmost'])
            self.assertEqual(self.pet_window().rootObject().property('color').alpha(), 0)
            capture = self.pet_window().rootObject().grabToImage()
            self.wait(lambda: not capture.image().isNull())
            self.assertEqual(capture.image().pixelColor(0, 0).alpha(), 0)
            self.assertGreater(capture.image().pixelColor(140, 200).alpha(), 0)
            self.activate()
            canvas_window = self.host._views[self.canvas.handle]
            _mouseMove(canvas_window, QPoint(350, 300))
            _mouseMove(canvas_window, QPoint(-20, -20))
            self.wait(lambda: self.pet_visible() and not self.canvas_visible())
            self.assertIsNone(self.pet.status()['activeSession'])

        def test_canvas_shown_under_click_pointer_accepts_direct_leave(self):
            window = self.pet_window()
            _mouseMove(window, self.hit_point())
            self.activate()
            canvas_window = self.host._views[self.canvas.handle]
            # The click already positioned the pointer where the new canvas appears;
            # do not synthesize a second pointer entry before leaving it.
            _mouseMove(canvas_window, QPoint(-20, -20))
            self.wait(lambda: self.pet_visible() and not self.canvas_visible())

        def test_drag_moves_pet_without_opening_canvas_and_saves_position(self):
            window = self.pet_window()
            before = self.host.view_status(self.pet.handle)
            start = self.hit_point()
            _mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
            for offset in (20, 40, 70):
                _mouseMove(window, start + QPoint(offset, 20))
                QTest.qWait(30)
            _mouseRelease(window, Qt.LeftButton, Qt.NoModifier, start + QPoint(70, 20))
            self.wait(lambda: self.pet.position != (before['x'], before['y']))
            QTest.qWait(100)
            self.assertFalse(self.canvas_visible())
            self.assertIsNone(self.pet.status()['activeSession'])
            import json
            self.wait(lambda: self.pet._data_path.exists())
            saved = json.loads(self.pet._data_path.read_text())
            self.assertEqual((saved['x'], saved['y']), self.pet.position)

        def test_idle_animation_does_not_move_hit_target_or_turn_click_into_drag(self):
            window = self.pet_window()
            start = self.hit_point()
            _mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
            QTest.qWait(500)
            self.assertEqual(self.hit_point(), start)
            _mouseRelease(window, Qt.LeftButton, Qt.NoModifier, start)
            self.wait(lambda: self.canvas_visible())

        def test_drag_crosses_screen_and_saves_final_queued_position(self):
            import json
            import threading
            from unittest.mock import patch
            from types import SimpleNamespace
            from PySide6.QtCore import QRect
            screens = [SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1040)),
                       SimpleNamespace(availableGeometry=lambda: QRect(-1600, 0, 1600, 860))]
            self.pet.move((100, 100), self.context)
            entered, release = threading.Event(), threading.Event()
            original = self.pet.move
            calls = []
            def slow_move(point, context, constrain=True):
                calls.append((point, constrain))
                if len(calls) == 1:
                    entered.set()
                    self.assertTrue(release.wait(3))
                return original(point, context, constrain)
            with patch('polaris_platform.desktop.window.QGuiApplication.screens', return_value=screens), patch.object(self.pet, 'move', side_effect=slow_move):
                self.pet.bridge.beginDrag(150, 150)
                self.pet.bridge.dragTo(-50, 150)
                self.wait(entered.is_set)
                self.pet.bridge.dragTo(-250, 250)
                self.pet.bridge.dragTo(-550, 350)
                self.pet.bridge.endDrag()
                release.set()
                self.wait(lambda: not self.pet.bridge._drag_worker)
            self.assertEqual(self.pet.position, (-600, 300))
            self.assertEqual(calls[0][1], False)
            self.assertEqual(calls[-1], ((-600, 300), True))
            saved = json.loads(self.pet._data_path.read_text())
            self.assertEqual(saved, {'x': -600, 'y': 300})
            self.assertFalse(self.canvas_visible())

        def test_canvas_stop_and_window_restart_restore_pet(self):
            self.activate()
            self.runtime.stop_component('canvas')
            self.wait(self.pet_visible)
            self.runtime.start_component('canvas')
            self.activate()
            self.runtime.stop_component('window')
            self.wait(lambda: self.pet.status()['waitingForWindow'])
            self.runtime.start_component('window')
            self.wait(lambda: self.pet_visible() and not self.pet.status()['waitingForWindow'])
            self.assertFalse(self.pet.status()['waitingForWindow'])

        def test_revoked_status_query_preserves_live_session_until_normal_dismissal(self):
            from polaris_platform.protocol import PlatformError
            self.activate()
            session = self.pet.status()['activeSession']
            self.runtime.revoke('pet', 'window', 'status')
            for _ in range(2):
                with self.assertRaises(PlatformError) as caught:
                    self.pet.monitor_session()
                self.assertEqual(caught.exception.code, 'permission_required')
                self.assertEqual(self.pet.status()['activeSession'], session)
                self.assertTrue(self.canvas_visible())
                self.assertFalse(self.pet_visible())
            # Both the pet's 200 ms monitor and canvas's 400 ms monitor execute.
            deadline = time.monotonic() + .8
            while time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertEqual(self.pet.status()['activeSession'], session)
            self.assertEqual(self.canvas.status()['sessionId'], session)
            self.assertTrue(self.canvas_visible())
            self.runtime.grant('pet', 'window', 'status')
            self.pet.monitor_session()
            self.assertEqual(self.pet.status()['activeSession'], session)
            self.call('canvas', 'hide')
            self.wait(lambda: self.pet_visible() and self.pet.status()['activeSession'] is None)

        def test_stopping_pet_and_revoking_restore_permission_never_revive_it(self):
            self.activate()
            self.runtime.revoke('pet', 'window', 'show')
            self.call('canvas', 'hide')
            QTest.qWait(450)
            self.assertFalse(self.pet_visible(), 'Restoration must honor current revoked window permission')
            self.runtime.stop_component('pet')
            self.call('canvas', 'show')
            self.call('canvas', 'hide')
            QTest.qWait(450)
            self.assertEqual(self.runtime.status('pet')['state'], 'stopped')
            self.assertIsNone(self.pet.handle)

    unittest.main()
