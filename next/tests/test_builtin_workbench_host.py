"""Built-in application registration and selection use the real runtime."""
import json
import os
import subprocess
import sys
import unittest

class BuiltinHostTest(unittest.TestCase):
    def test_builtin_lifecycle_and_selection(self):
        code = r'''
import json,tempfile
from pathlib import Path
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from polaris_platform.application import Application
from polaris_platform.bootstrap import build,default_config
from polaris_platform.desktop.application_host import ApplicationHost
from polaris_platform.builtin_apps.workbench import WORKBENCH_ID
app=QGuiApplication([]);runtime=build(default_config()); events=[]
class Builtin(Application):
    def __init__(self): super().__init__('工作台',application_id=WORKBENCH_ID)
    def start(self,port): super().start(port);events.append('start')
    def stop(self): events.append('stop');super().stop()
class View:
    def __init__(self,parent,header): self.active=[];self.closed=False
    def set_active(self,active): self.active.append(active)
    def selected_from_input(self): pass
    def close(self): self.closed=True
with tempfile.TemporaryDirectory() as temp:
    host=ApplicationHost(runtime);builtin=Builtin();host.register_builtin(builtin,View,component_type='org.polaris.workbench',version='1');host.configure(Path(temp))
    assert runtime.status(WORKBENCH_ID)['state']=='running'
    assert runtime.status(WORKBENCH_ID)['componentType']=='org.polaris.workbench'
    assert json.loads(host.selectedJson)['applicationId']==WORKBENCH_ID
    assert json.loads(host.applicationsJson)[0]['builtin'] is True
    parent=QQuickItem();header=QQuickItem();host.attachView(parent);host.attachBuiltinHeader(header);host.set_presentation_active(True)
    view=host._views[WORKBENCH_ID];assert view.active[-1]
    host.select('');assert not view.active[-1] and runtime.status(WORKBENCH_ID)['state']=='running'
    assert json.loads(host.selectedJson)=={}
    host.select(WORKBENCH_ID);assert view.active[-1]
    package=Path(temp)/'package';package.mkdir()
    (package/'polaris-application.json').write_text(json.dumps({'id':'fixture.app','name':'Fixture','version':'1',
        'entry':{'adapter':'qt-quick','file':'Main.qml'},'requires':{}}))
    (package/'Main.qml').write_text('import QtQuick\nItem {}')
    host.installDirectory(str(package))
    assert runtime.status(WORKBENCH_ID)['state']=='running' and events==['start']
    assert host._views[WORKBENCH_ID] is view and not view.closed and not view.active[-1]
    host.select(WORKBENCH_ID);assert host._views[WORKBENCH_ID] is view and view.active[-1]
    runtime.stop_application(WORKBENCH_ID);host._update_views();assert not view.active[-1]
    assert runtime.status(WORKBENCH_ID)['state']=='stopped'
    host.select(WORKBENCH_ID);assert view.active[-1] and runtime.status(WORKBENCH_ID)['state']=='running'
    host.set_presentation_active(False);assert runtime.status(WORKBENCH_ID)['state']=='running'
    host.close();assert view.closed and events==['start','stop','start']
    runtime.stop_application(WORKBENCH_ID);assert events==['start','stop','start','stop']
for row in reversed(runtime.snapshot()):
    if row['state']=='running':runtime.stop_component(row['id'],persist=False)
'''
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
        result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
