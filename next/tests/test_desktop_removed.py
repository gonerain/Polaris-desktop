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
            for identity in json.loads(sys.argv[4]):
                runtime.uninstall_component(identity)
        result['ids'] = sorted(item['id'] for item in runtime.snapshot())
        result['removed'] = sorted(runtime.removed_installations())
        result['managerVisible'] = runtime.component_instance('manager').status()['visible']
        result['managerState'] = runtime.status('manager')['state']
    except Exception as error:
        result['error'] = repr(error)
    finally:
        QTimer.singleShot(30, app.quit)
QTimer.singleShot(100, exercise)
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
                self.assertEqual(payload['managerVisible'], phase != 'remove')
