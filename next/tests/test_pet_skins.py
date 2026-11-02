"""Real QML skin slots with fake pet actions and no business calls."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

class PetSkinProcessTests(unittest.TestCase):
    def test_skin_slots(self):
        if importlib.util.find_spec('PySide6') is None:
            self.skipTest('Qt unavailable')
        result = subprocess.run([sys.executable,__file__,'qt'],env=dict(os.environ,
            QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software'),capture_output=True,text=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__ == '__main__' and sys.argv[-1] == 'qt':
    import tempfile
    from types import SimpleNamespace
    from PySide6.QtCore import QObject, Property, Slot, QPoint, QPointF, QUrl, Qt
    from PySide6.QtGui import QGuiApplication, QCursor
    from PySide6.QtTest import QTest
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from polaris_platform.desktop.window import WindowHost
    from polaris_platform.desktop.pet import Pet
    BASE=Path(__file__).resolve().parent
    class Actions(QObject):
        clicked=0
        ended=0
        dragged=0
        @Property(str,constant=True)
        def notice(self): return ''
        @Slot(result=QPointF)
        def pointerPosition(self): return QPointF(QCursor.pos())
        @Slot(float,float)
        def beginDrag(self,x,y): pass
        @Slot(float,float)
        def dragTo(self,x,y): self.dragged+=1
        @Slot()
        def endDrag(self): self.ended+=1
        @Slot()
        def activate(self): self.clicked+=1
        @Slot()
        def management(self): pass
        @Slot()
        def quit(self): pass
    class SkinTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls): cls.app=QGuiApplication([])
        def setUp(self):
            self.actions=Actions()
            self.host=WindowHost()
            self.host.start(SimpleNamespace(id='window',instance='test'))
            self.pet=Pet(skin_source=BASE/'fixtures/PetSkinOne.qml')
            self.handle=self.host.create_view(Path(__file__).resolve().parents[1]/'polaris_platform/desktop/Pet.qml','fixture',
                (280,320),self.pet.properties,{'petActions':self.actions},self.pet.window_options)
            self.window=self.host._views[self.handle]
            self.root=self.window.rootObject()
            self.wait(lambda:self.root.property('skinReady'))
        def tearDown(self):
            self.host.stop()
            self.app.processEvents()
        def wait(self,predicate):
            for _ in range(100):
                if predicate(): return
                QTest.qWait(10)
            self.assertTrue(predicate())
        def move(self,point):
            QCursor.setPos(self.window.mapToGlobal(point));QTest.mouseMove(self.window,point);QTest.qWait(10)
        def press(self,point):
            self.move(point);QTest.mousePress(self.window,Qt.LeftButton,Qt.NoModifier,point)
        def release(self,point): QTest.mouseRelease(self.window,Qt.LeftButton,Qt.NoModifier,point)
        def skin(self,name='petSkinOne'): return self.root.findChild(QObject,name)
        def change(self,name):
            self.root.setProperty('skinSource',QUrl.fromLocalFile(str(BASE/'fixtures'/name)))
            self.wait(lambda:self.root.property('skinReady'))
        def test_real_mouse_actions_completion_and_drag_priority(self):
            self.move(QPoint(140,210))
            self.assertEqual(self.root.property('actionName'),'greetOne')
            stale=self.root.property('requestId')
            self.press(QPoint(140,210));QTest.qWait(60)
            self.assertEqual(self.root.property('actionName'),'pressOne','finished press holds its last pose until release')
            self.assertEqual(self.skin().property('observedAction'),'pressOne')
            self.assertAlmostEqual(self.skin().findChild(QObject,'skinVisualOne').property('opacity'),0.6,places=2)
            self.skin().finished.emit(stale)
            self.assertEqual(self.root.property('actionName'),'pressOne')
            self.move(QPoint(160,210))
            self.assertEqual(self.root.property('actionName'),'liftOne')
            lift=self.root.property('requestId')
            self.skin().finished.emit(lift)
            self.assertEqual(self.root.property('actionName'),'dragOne')
            self.move(QPoint(20,290))
            self.assertEqual(self.root.property('actionName'),'dragOne')
            self.release(QPoint(20,290))
            self.assertEqual(self.root.property('actionName'),'dropOne')
            self.assertEqual(self.actions.clicked,0)
            self.skin().finished.emit(self.root.property('requestId'))
            self.assertEqual(self.root.property('actionName'),'restOne')
        def test_skin_switch_changes_mapping_mask_and_cancels_old_gesture(self):
            self.press(QPoint(140,210));self.move(QPoint(160,210))
            old=self.root.property('requestId');ended=self.actions.ended
            self.change('PetSkinTwo.qml')
            self.assertGreater(self.actions.ended,ended)
            self.assertFalse(self.root.property('dragging'))
            self.assertEqual(self.root.property('actionName'),'restTwo')
            self.release(QPoint(160,210))
            self.assertEqual(self.actions.clicked,0)
            self.assertTrue(self.window.mask().contains(QPoint(50,75)))
            self.assertFalse(self.window.mask().contains(QPoint(140,210)))
            self.move(QPoint(50,75))
            self.assertEqual(self.root.property('actionName'),'restTwo','missing hover slot falls back to this skin idle')
            self.press(QPoint(50,75));QTest.qWait(60)
            self.assertEqual(self.skin('petSkinTwo').property('observedAction'),'pressTwo')
            self.assertAlmostEqual(self.skin('petSkinTwo').findChild(QObject,'skinVisualTwo').property('opacity'),0.8,places=2)
            self.release(QPoint(50,75))
            self.assertEqual(self.root.property('actionName'),'restTwo')
            self.assertEqual(self.actions.clicked,1)
            token=self.root.property('requestId')
            self.skin('petSkinTwo').finished.emit(old)
            self.assertEqual(self.root.property('requestId'),token)
        def test_large_idle_collection_waits_for_skin_completion_and_is_interrupted(self):
            self.move(QPoint(5,300))
            self.assertEqual(len(self.root.property('idleAnimations').toVariant()),40)
            self.skin().setProperty('idleInterval',30)
            self.wait(lambda:self.root.property('idleIndex')>=0)
            token=self.root.property('requestId')
            QTest.qWait(100)
            self.assertEqual(self.root.property('requestId'),token,'long idle variants must not be cut by the idle timer')
            self.move(QPoint(140,210))
            self.assertEqual(self.root.property('actionName'),'greetOne')
            self.skin().finished.emit(token)
            self.assertEqual(self.root.property('actionName'),'greetOne')
            self.host.hide_view(self.handle)
            self.assertEqual(self.root.property('actionName'),'restOne')
            QTest.qWait(100)
            self.assertEqual(self.root.property('idleIndex'),-1)
        def test_bad_path_and_loaded_bad_contract_restore_default(self):
            for contents in (None,'import QtQuick\nItem {}', (BASE/'fixtures/PetSkinOne.qml').read_text().replace('{x:90,y:150,width:100,height:120,radius:30}', '{bad:true}')):
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'Broken.qml'
                    if contents is not None: path.write_text(contents)
                    self.root.setProperty('skinSource',QUrl.fromLocalFile(str(path)))
                    self.wait(lambda:self.root.property('skinReady') and 'PetDefaultSkin.qml' in self.root.property('skinSource').toString())
                    self.assertTrue(self.root.property('skinError'))
                    self.assertTrue(self.window.mask().contains(QPoint(140,210)))
    unittest.main(argv=[sys.argv[0]],defaultTest='SkinTests')
