"""Exercise the desktop's default installation policy without external network or account data."""
import json
import os
import sys
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from components.manager.defaults import DefaultInstallations, configured_sources
from components.sources import create_sources
from polaris_platform.bootstrap import build, default_config, load_factory
from polaris_platform.component import Component


class DefaultInstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.rt = build(default_config(), state_dir=self.base/'state')
        self.rt.install({'id': 'sources', 'name': 'Sources', 'version': '1', 'platformApi': 1,
                         'entry': {'mode': 'inprocess'}}, lambda: create_sources(self.rt))
        self.rt.start_component('sources')
        self.installer = DefaultInstallations(self.rt, self.rt.component_instance('sources'))
        self.addCleanup(self.stop)

    def stop(self):
        self.installer.cancelled.set()
        for row in reversed(self.rt.snapshot()):
            if row['state'] in ('running', 'failed'):
                self.rt.stop_component(row['id'], persist=False)

    def plugin(self, name):
        root = self.base/name
        plugin = root/'plugins'/name
        plugin.mkdir(parents=True)
        module = 'official_fixture_' + name
        manifest = dict(id=name, name=name, platformApi=1, version='1',
                        entry=dict(mode='inprocess', factory=module+':create'))
        (plugin/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (plugin/(module+'.py')).write_text(
            'from polaris_platform.sdk import Component\ndef create():\n c=Component()\n'
            ' c.operation("value")(lambda: "from official source")\n return c\n', encoding='utf-8')
        (root/'polaris-source.json').write_text(json.dumps(dict(schemaVersion=1, name=name,
             components=[{'path':'plugins/'+name}])), encoding='utf-8')
        return dict(name=name, component=name, location=str(root), legacyDirectory=name,
                    legacyFactory=module+':create'), manifest

    def settle(self):
        deadline = time.monotonic() + 5
        while self.installer.pending and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.installer.pending)

    def test_offline_source_stays_visible_and_retry_does_not_duplicate_install(self):
        spec = dict(name='retry', component='retry', location=str(self.base/'retry'))
        self.installer.configure([spec])
        self.settle()
        source, = self.installer.control.sources()
        self.assertEqual(source['location'], spec['location'])
        self.assertIn(source['id'], self.installer.errors)
        self.plugin('retry')
        self.installer.request(source['id'])
        self.settle()
        before = self.rt.status('retry')
        self.assertEqual(before['state'], 'running')
        self.assertFalse(self.installer.errors)
        self.rt.stop_component('retry')
        self.installer.configure([spec])
        self.assertEqual(self.rt.status('retry')['state'], 'stopped')
        self.assertEqual(self.rt.status('retry')['installation'], before['installation'])
        self.rt.uninstall_component('retry')
        self.installer.configure([spec])
        self.assertFalse(self.installer.pending)
        self.assertIn('retry', self.rt.removed_installations())
        self.assertEqual(len(self.installer.control.sources()), 1)

    def test_migrate_missing_bundled_directory_without_replacing_another_install(self):
        specs = []
        for name in ('enabled', 'disabled', 'custom'):
            spec, manifest = self.plugin(name)
            specs.append(spec)
            old_path = self.base/'next'/'components'/name if name != 'custom' else self.base/'my-plugins'/name
            legacy = Component()
            legacy.operation('value')(lambda p, c: 'legacy')
            self.rt.install(manifest, lambda c=legacy: c, installation_id='existing-'+name, directory=old_path)
            self.rt.start_component(name)
            self.rt.grant('runtime', name, 'value')
            if name != 'custom':
                self.rt.stop_component(name, persist=(name=='disabled'))
        self.installer.configure(specs)
        self.settle()
        self.assertFalse(self.installer.errors)
        installed = {r['manifest']['id']:r for r in self.rt.export_installations()}
        for name in ('enabled', 'disabled', 'custom'):
            self.assertEqual(installed[name]['installationId'], 'existing-'+name)
            self.assertEqual(installed[name]['autostart'], name != 'disabled')
        self.assertIn('revisions', Path(installed['disabled']['directory']).parts)
        self.assertEqual(self.rt.status('disabled')['state'], 'stopped')
        self.assertEqual(self.rt.client('runtime').call('enabled', 'value', {}, self.rt.user_context('runtime')), 'from official source')
        self.assertEqual(self.rt.client('runtime').call('custom', 'value', {}, self.rt.user_context('runtime')), 'legacy')

    def test_failed_autostart_from_cache_only_directory_recovers_during_migration(self):
        spec, manifest = self.plugin('cached')
        module = spec['legacyFactory'].split(':')[0]
        old = self.base/'next'/'components'/'cached'
        (old/module/'__pycache__').mkdir(parents=True)
        self.addCleanup(sys.modules.pop, module, None)
        original_path = sys.path[:]
        self.addCleanup(setattr, sys, 'path', original_path)
        self.rt.install(manifest, load_factory(manifest, old, self.rt), directory=old, autostart=True)
        with self.assertRaisesRegex(AttributeError, 'create'):
            self.rt.start_component('cached')
        self.assertIsNone(sys.modules[module].__file__)
        identity = self.rt.status('cached')['installation']
        self.installer.configure([spec])
        self.settle()
        self.assertFalse(self.installer.errors)
        self.assertEqual(self.rt.status('cached')['installation'], identity)
        self.rt.grant('runtime', 'cached', 'value')
        self.assertEqual(self.rt.client('runtime').call('cached', 'value', {}, self.rt.user_context('runtime')),
                         'from official source')

    def test_distribution_presets(self):
        self.assertEqual({s['component']:s['location'] for s in configured_sources({})},
            {'org.polaris.'+name: 'https://github.com/gonerain/Polaris-'+name+'.git' for name in ('agent','weixin','schedule')})
        self.assertEqual(configured_sources({'defaultSources': []}), [])
