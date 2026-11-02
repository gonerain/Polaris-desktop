"""Distribution entry points must not turn CLI/worker calls into GUI launches."""
import ast
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'next'))
from polaris_platform import __version__
from polaris_platform.metadata import APP_NAME, VERSION, DISPLAY_VERSION
from polaris_platform.transport import ProcessComponent


class EntrypointTests(unittest.TestCase):
    def test_version_single_source_without_qt(self):
        self.assertEqual(__version__, '0.1.0.0')
        script = '''
import importlib.abc, runpy, sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            raise AssertionError('CLI imported Qt')
sys.meta_path.insert(0, NoQt())
sys.argv = [sys.argv[1], '--version']
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'main.py')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f'{APP_NAME} {DISPLAY_VERSION}')
        self.assertIn('dynamic = ["version"]', (ROOT / 'next/pyproject.toml').read_text())
        self.assertIn('polaris_platform.metadata.VERSION', (ROOT / 'next/pyproject.toml').read_text())

    def test_help_and_explicit_headless(self):
        help_result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--help'], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('--headless', help_result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--headless', '--state-dir', directory], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({r['id'] for r in json.loads(result.stdout)}, {'authorization', 'collaboration', 'runtime'})
        rejected = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--bridge-stdio', '--endpoint', '/tmp/old-endpoint'], capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn('independent repository', rejected.stderr)

    def test_default_main_selects_gui_without_constructing_application(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('polaris_launcher_test', ROOT / 'main.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with patch('polaris_platform.__main__.main', return_value=17) as run:
            self.assertEqual(launcher.main(['--state-dir', '/tmp/example']), 17)
            run.assert_called_once_with(['--state-dir', '/tmp/example'], default_gui=True)

    def test_explicit_worker_runs_script_and_module_without_qt(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'worker_example.py'
            script.write_text("import json, sys\nprint(json.dumps({'argv':sys.argv[1:], 'qt': 'PySide6' in sys.modules}))\n", encoding='utf-8')
            for args in ([str(script), 'payload'], ['-m', 'worker_example', 'payload']):
                result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--component-python', *args], cwd=directory, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'argv':['payload'], 'qt':False})

    @unittest.skipIf(os.name == 'nt', 'POSIX source wrapper models the frozen executable')
    def test_frozen_python_process_component_uses_explicit_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            wrapper = directory / 'Polaris'
            wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(ROOT / 'main.py')) + ' "$@"\n')
            wrapper.chmod(0o700)
            script = directory / 'component.py'
            script.write_text("from polaris_platform.sdk import Component\nc=Component()\n@c.operation('echo')\ndef echo(value): return value\nc.run()\n")
            component = ProcessComponent({'entry': {'command':['{python}', 'component.py'], 'mode':'process'}}, directory)
            try:
                with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(wrapper)):
                    description = component.describe()
                self.assertIn('echo', description['operations'])
            finally:
                component.force_stop()

    def test_frozen_plugin_standard_library_baseline(self):
        import sysconfig
        source = (ROOT / 'Polaris.spec').read_text()
        baseline = source[source.index('# Platform imports'):source.index('# Generate the Windows')]
        namespace = dict(Path=Path, os=os, sys=sys, sysconfig=sysconfig,
                         collect_submodules=lambda name: [])
        exec(compile(baseline, 'Polaris.spec', 'exec'), namespace)
        imports = namespace['hiddenimports']
        for module in ('sqlite3', 'sqlite3.dbapi2', 'ctypes.wintypes', 'http.server', 'urllib.request'):
            self.assertIn(module, imports)
        self.assertNotIn('_tkinter', imports)
        self.assertFalse(any(name.startswith(('site-packages.', 'tkinter.', 'idlelib.', 'test.')) for name in imports))

    def test_spec_collects_only_new_default_application(self):
        source = (ROOT / 'Polaris.spec').read_text()
        ast.parse(source)
        self.assertNotIn("root / 'next' / 'integrations'", source)
        self.assertNotIn("root / 'next' / 'components'", source)
        self.assertIn('filevers=parts, prodvers=parts', source)
        self.assertNotIn('legacy_main.py', source)
        self.assertNotIn("('qml', 'qml')", source)


if __name__ == '__main__':
    unittest.main()
