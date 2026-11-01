"""Schedule plugin registration, local data and live authority boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'components' / 'schedule'


class ScheduleComponentTests(unittest.TestCase):
    def setUp(self):
        from polaris_platform.bootstrap import build, default_config
        from polaris_platform.component import Component
        from polaris_platform.bootstrap import load_factory
        self.directory = tempfile.TemporaryDirectory()
        manifest = json.loads((PLUGIN / 'manifest.json').read_text())
        manifest['entry']['kwargs'] = {'data_dir': self.directory.name}
        self.runtime = build(default_config())
        self.runtime.install({'id': 'user', 'name': 'User', 'version': '1', 'platformApi': 1,
                              'entry': {'mode': 'inprocess'}}, Component)
        self.runtime.start_component('user')
        self.runtime.install(manifest, load_factory(manifest, PLUGIN, self.runtime))
        self.runtime.start_component('org.polaris.schedule')
        self.identity = manifest['id']
        for name in self.runtime.status(self.identity)['description']['operations']:
            self.runtime.grant('user', self.identity, name)
        self.context = self.runtime.user_context('user')

    def tearDown(self):
        for record in reversed(self.runtime.snapshot()):
            if record['state'] == 'running':
                self.runtime.stop_component(record['id'])
        self.directory.cleanup()

    def call(self, operation, **params):
        return self.runtime.client('user').call(self.identity, operation, params, context=self.context)

    def test_business_without_view_and_restart_persistence(self):
        task = self.call('add', title='Plan', date='2026-10-30')
        self.call('add_subtask', identity=task['id'], title='First step')
        self.call('update', identity=task['id'], important=True, notes='Keep this')
        self.assertEqual(self.call('get')['tasks'][0]['notes'], 'Keep this')
        self.assertEqual(self.call('release_view', handle='missing'), {'released': False})
        self.runtime.stop_component(self.identity)
        self.runtime.start_component(self.identity)
        self.context = self.runtime.user_context('user')
        restored = self.call('get')['tasks'][0]
        self.assertTrue(restored['important'])
        self.assertEqual(restored['subtasks'][0]['title'], 'First step')

    def test_revoked_mutation_and_read_do_not_bypass_context(self):
        from polaris_platform.protocol import PlatformError
        self.call('add', title='Before')
        self.runtime.revoke('user', self.identity, 'add')
        with self.assertRaises(PlatformError):
            self.call('add', title='Denied')
        self.assertEqual(len(self.call('get')['tasks']), 1)
        self.runtime.revoke('user', self.identity, 'get')
        with self.assertRaises(PlatformError):
            self.call('get')

    def test_descriptor_is_generic_native_contract(self):
        description = self.runtime.status(self.identity)['description']
        self.assertEqual(description['dependencies'], [])
        self.assertEqual(description['views'][0]['adapter'], 'qt-quick-item')
        self.assertEqual(description['operations']['create_view']['profile'], 'qt-native')

    def test_import_and_business_are_qt_lazy(self):
        code = ("import sys,tempfile;sys.path[:0]=" + repr([str(ROOT), str(PLUGIN)]) + ";"
                "from polaris_schedule import create;"
                "d=tempfile.TemporaryDirectory();c=create(data_dir=d.name);c.get();"
                "assert not any(k.startswith('PySide6') for k in sys.modules)")
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schedule_config_starts_headless_business(self):
        from polaris_platform.bootstrap import build
        config = json.loads((ROOT / 'config.schedule.json').read_text())
        self.assertEqual(len(config['components']), 4)
        config['components'][-1] = {'directory': str(PLUGIN), 'manifest': json.loads((PLUGIN / 'manifest.json').read_text()), 'autostart': True}
        config['components'][-1]['manifest']['entry']['kwargs'] = {'data_dir': self.directory.name}
        runtime = build(config, ROOT)
        try:
            self.assertEqual(runtime.status(self.identity)['state'], 'running')
            installed = next(row for row in runtime.export_installations()
                             if row['manifest']['id'] == self.identity)
            self.assertTrue(installed['autostart'])
            self.assertNotIn('defer', installed['manifest']['entry'])
        finally:
            for record in reversed(runtime.snapshot()):
                if record['state'] == 'running':
                    runtime.stop_component(record['id'])


if __name__ == '__main__':
    unittest.main()
