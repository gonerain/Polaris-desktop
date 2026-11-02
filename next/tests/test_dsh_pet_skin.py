"""Reuse actual WebP frames through the new skin contract, without business calls."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

class DshSkinProcessTests(unittest.TestCase):
    def test_real_clip_cycles_and_input_envelope(self):
        if importlib.util.find_spec('PySide6') is None:
            self.skipTest('Qt unavailable')
        result=subprocess.run([sys.executable,__file__,'qt'],env=dict(os.environ,
            QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software'),capture_output=True,text=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__' and sys.argv[-1]=='qt':
    import time
    from PySide6.QtCore import QObject, Property, Slot, QPointF, QRectF, QRect
    from PySide6.QtGui import QGuiApplication,QCursor,QImage,QImageReader,QPainter
    from PySide6.QtTest import QTest
    ROOT=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(ROOT/'next'))
    from polaris_platform.desktop.window import WindowHost
    from polaris_platform.desktop.pet import Pet
    class Actions(QObject):
        @Property(str,constant=True)
        def notice(self):return ''
        @Slot(result=QPointF)
        def pointerPosition(self):return QPointF(QCursor.pos())
        @Slot()
        def endDrag(self):pass
    app=QGuiApplication([])
    host=WindowHost();host.start(None)
    pet=Pet()
    actions=Actions()
    handle=host.create_view(ROOT/'next/components/pet/Pet.qml','fixture',pet.size,
        pet.properties,{'petActions':actions},pet.window_options)
    window=host._views[handle];root=window.rootObject()
    def wait(predicate,seconds=5):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:QTest.qWait(10)
        assert predicate(), 'skin state did not settle'
    try:
        wait(lambda:root.property('skinReady'))
        loader=root.findChild(QObject,'petSkinLoader');skin=loader.property('item')
        frames=root.findChild(QObject,'dshSkinFrames')
        assert frames is not None and frames.property('frameCount')==80
        completions=[];skin.finished.connect(lambda token:completions.append(token))
        root.requestAction('hoverEnter',None)
        wave=root.property('requestId');started=time.monotonic()
        assert root.property('actionName')=='wave'
        wait(lambda:wave in completions)
        assert time.monotonic()-started>=2.3, 'reset/source changes must not fake a completed cycle'
        assert root.property('actionName')=='idle'
        root.requestAction('hoverEnter',None)
        wait(lambda:frames.property('currentFrame')>=3)
        cancelled=root.property('requestId')
        root.requestAction('hoverEnter',None)
        QTest.qWait(150)
        assert cancelled not in completions and root.property('actionName')=='wave'
        root.requestAction('drag',None)
        observed=[]
        frames.currentFrameChanged.connect(lambda:observed.append(frames.property('currentFrame')))
        wait(lambda:any(b<a for a,b in zip(observed,observed[1:])),seconds=5)
        assert root.property('actionName')=='drag' and frames.property('playing')
        root.requestAction('drop',None)
        dropped=root.property('requestId')
        wait(lambda:dropped in completions)
        assert root.property('actionName')=='idle'
        host.hide_view(handle);QTest.qWait(30)
        frozen=frames.property('currentFrame');QTest.qWait(250)
        assert not frames.property('playing') and frames.property('currentFrame')==frozen
        host.show_view(handle);QTest.qWait(30)
        # Offline alpha coverage check: selected clips plus the transform endpoints.
        mask=QImage(280,320,QImage.Format_RGBA8888);mask.fill(0)
        painter=QPainter(mask);painter.setClipRegion(window.mask());painter.fillRect(QRect(0,0,280,320),'white');painter.end()
        outside=[i for i,a in enumerate(bytes(mask.constBits())[3::4]) if not a]
        image=QImage(280,320,QImage.Format_RGBA8888)
        def covered(frame,scale=1,dy=0):
            image.fill(0);p=QPainter(image);p.translate(40,112+dy);p.translate(100,184);p.scale(scale,1/scale);p.translate(-100,-184)
            p.drawImage(QRectF(0,0,200,200),frame);p.end()
            alpha=bytes(image.constBits())[3::4]
            assert not any(alpha[i]>16 for i in outside), 'visible frame extends beyond the declared input envelope'
        for name in ('idle','wave','drag','stretch','puzzle','glance','drowsy'):
            reader=QImageReader(str(ROOT/'next/components/pet/skins/dshpet'/f'{name}.webp'))
            for _ in range(reader.imageCount()):
                frame=reader.read();assert not frame.isNull()
                covered(frame,.96 if name=='drag' else 1,-4 if name=='drag' else 0)
        poster=QImage(str(ROOT/'next/components/pet/skins/dshpet/poster.webp'))
        for scale in (.96,.98,1,1.06):covered(poster,scale)
        covered(poster,.96,-4)
    finally:
        host.stop();app.processEvents()
