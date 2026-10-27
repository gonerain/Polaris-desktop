"""Exercise the real startup/shutdown path in isolated offscreen subprocesses."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class DesktopLifecycleTests(unittest.TestCase):
    def run_isolated(self, script, directory):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        return subprocess.run([sys.executable, "-c", script, directory],
                              cwd=Path(__file__).resolve().parent, env=env,
                              capture_output=True, text=True, timeout=15)

    def test_real_entry_point_saves_exits_and_releases_lock(self):
        script = '''
import sys
from unittest.mock import patch
from PySide6.QtCore import QTimer, QObject
import main
original = main.create_engine
def create_engine(**options):
    engine = original(**options)
    window = engine.rootObjects()[0]
    store = window.findChild(QObject, "calendarTaskStore")
    store.addTask("Persistent task")
    QTimer.singleShot(100, window.requestQuit)
    return engine
with patch.object(main.QStandardPaths, "writableLocation", return_value=sys.argv[1]), \\
     patch.object(main, "create_engine", side_effect=create_engine):
    raise SystemExit(main.main())
'''
        with TemporaryDirectory() as directory:
            first = self.run_isolated(script, directory)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue((Path(directory) / "tasks.json").exists())
            self.assertFalse((Path(directory) / "app.lock").exists())
            second = self.run_isolated(script, directory)
            self.assertEqual(second.returncode, 0, second.stderr)
            import json
            data = json.loads((Path(directory) / "tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(map(len, data["days"].values())), 2)

    def test_duplicate_start_is_rejected_without_a_window(self):
        from PySide6.QtCore import QLockFile
        script = '''
import sys
from unittest.mock import patch
import main
with patch.object(main.QStandardPaths, "writableLocation", return_value=sys.argv[1]), \\
     patch.object(main, "_show_startup_error", side_effect=lambda text: print("LOCKED")):
    raise SystemExit(main.main())
'''
        with TemporaryDirectory() as directory:
            lock = QLockFile(str(Path(directory) / "app.lock"))
            self.assertTrue(lock.tryLock(0))
            try:
                result = self.run_isolated(script, directory)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("LOCKED", result.stdout)
                self.assertFalse((Path(directory) / "tasks.json").exists())
            finally:
                lock.unlock()
