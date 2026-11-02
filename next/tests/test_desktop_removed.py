"""GUI restart coverage uses isolated Qt processes and temporary installation state."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Optional PySide6 is not installed')
class RemovedDesktopProcessTests(unittest.TestCase):
    def test_removed_defaults_stay_removed_and_manager_remains_accessible(self):
        self.check_restarts(['canvas', 'pet'])

    def test_removed_window_preserves_management_entry_after_restart(self):
        self.check_restarts(['window'])

    def test_recovery_with_public_operations_only_manager(self):
        script = r'''
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from polaris_platform.bootstrap import from_file
from polaris_platform.component import Component
from polaris_platform.desktop import run
app = QGuiApplication([])
runtime = from_file(Path('next/config.headless.json'))
class PublicManager(Component):
    def __init__(self):
        super().__init__()
        self.visible = False
        self.operation('show')(self.display)
        self.operation('hide')(lambda p,c: setattr(self,'visible',False))
        self.operation('status')(lambda p,c: {'visible':self.visible})
    def display(self,p,c):
        self.visible = True
        return {'visible':True}
manager = PublicManager()
runtime.install({'id':'manager','name':'manager','version':'1','platformApi':1,'entry':{'mode':'inprocess'}},lambda:manager)
# Mark the normal entry as explicitly removed before desktop assembly.
runtime.install({'id':'pet','name':'pet','version':'1','platformApi':1,'entry':{'mode':'inprocess'}}, Component)
runtime.uninstall_component('pet')
QTimer.singleShot(150,app.quit)
runtime.manager_config['defaultSources'] = []
result = run(runtime)
assert result == 0 and manager.visible
assert not hasattr(manager,'bridge') and not hasattr(manager,'show')
'''
        process = subprocess.run([sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'), capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def check_restarts(self, removed):
        script = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from polaris_platform.bootstrap import from_file
from polaris_platform.desktop import run
app = QGuiApplication([])
runtime = from_file(Path(sys.argv[1]), state_dir=sys.argv[2])
result = {}
def exercise():
    try:
        if sys.argv[3] == 'remove':
            runtime.stop_component('sources')
            for identity in json.loads(sys.argv[4]):
                runtime.uninstall_component(identity)
        result['ids'] = sorted(item['id'] for item in runtime.snapshot())
        result['removed'] = sorted(runtime.removed_installations())
        result['managerVisible'] = runtime.component_instance('manager').status()['visible']
        result['managerState'] = runtime.status('manager')['state']
        result['sourcesState'] = runtime.status('sources')['state']
    except Exception as error:
        result['error'] = repr(error)
    finally:
        QTimer.singleShot(30, app.quit)
QTimer.singleShot(100, exercise)
runtime.manager_config['defaultSources'] = []
result['exit'] = run(runtime)
print(json.dumps(result))
'''
        config = Path(__file__).resolve().parents[1] / 'config.headless.json'
        with tempfile.TemporaryDirectory() as directory:
            for phase in ('remove', 'restart', 'restart'):
                process = subprocess.run(
                    [sys.executable, '-c', script, str(config), directory, phase, json.dumps(removed)],
                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_DATA_HOME=directory),
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                payload = json.loads(process.stdout)
                self.assertNotIn('error', payload)
                self.assertEqual(payload['exit'], 0)
                for identity in removed:
                    self.assertNotIn(identity, payload['ids'])
                self.assertEqual(payload['removed'], sorted(removed))
                self.assertEqual(payload['managerState'], 'running')
                self.assertNotEqual(payload['sourcesState'], 'running')
                self.assertEqual(payload['managerVisible'], phase != 'remove')
