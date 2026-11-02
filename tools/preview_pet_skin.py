#!/usr/bin/env python3
"""Isolated skin preview; no canvas, model, messaging or persistent state."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('skin', nargs='?', type=Path, default=None)
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--seconds', type=float, default=0)
parser.add_argument('--screenshot', type=Path)
args = parser.parse_args()
if args.offscreen:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['QT_QUICK_BACKEND'] = 'software'
sys.path.insert(0, str(ROOT/'next'))
from PySide6.QtCore import QObject, Property, Slot, QPointF, QTimer
from PySide6.QtGui import QGuiApplication, QCursor
from polaris_platform.desktop.pet import Pet
from polaris_platform.desktop.window import WindowHost

app = QGuiApplication([])
app.setQuitOnLastWindowClosed(False)
host = WindowHost()
host.start(None)
class PreviewActions(QObject):
    origin = None
    @Property(str, constant=True)
    def notice(self): return ''
    @Slot(result=QPointF)
    def pointerPosition(self): return QPointF(QCursor.pos())
    @Slot(float,float)
    def beginDrag(self,x,y):
        state = host.view_status(handle)
        self.origin=(x,y,state['x'],state['y'])
    @Slot(float,float)
    def dragTo(self,x,y):
        if self.origin:
            sx,sy,px,py=self.origin
            host.move_view(handle,px+x-sx,py+y-sy,False)
    @Slot()
    def endDrag(self):
        if self.origin and host.running:
            state=host.view_status(handle)
            host.move_view(handle,state['x'],state['y'],True)
        self.origin=None
    @Slot()
    def activate(self): pass
    @Slot()
    def management(self): pass
    @Slot()
    def quit(self): app.quit()
actions = PreviewActions()
pet = Pet(skin_source=args.skin)
handle = host.create_view(ROOT/'next/components/pet/Pet.qml', 'Polaris · 皮肤预览', pet.size,
    pet.properties, {'petActions':actions}, pet.window_options)
if args.screenshot:
    def capture():
        args.screenshot.parent.mkdir(parents=True,exist_ok=True)
        host._views[handle].grabWindow().save(str(args.screenshot))
    QTimer.singleShot(500,capture)
if args.seconds>0:
    QTimer.singleShot(round(args.seconds*1000),app.quit)
app.aboutToQuit.connect(host.stop)
app.exec()
