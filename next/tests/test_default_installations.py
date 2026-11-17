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

    def test_one_source_can_install_multiple_targets_without_reinstalling_removed(self):
        first, _ = self.plugin('first')
        second, _ = self.plugin('second')
        root = Path(first['location'])
        import shutil
        shutil.copytree(Path(second['location']) / 'plugins' / 'second', root / 'plugins' / 'second')
        (root / 'polaris-source.json').write_text(json.dumps(dict(schemaVersion=1, name='Both',
            components=[{'path': 'plugins/first'}, {'path': 'plugins/second'}])))
        spec = dict(name='Both', location=str(root), components=[{'component': 'first'}, {'component': 'second'}])
        self.installer.configure([spec])
        self.settle()
        self.assertFalse(self.installer.errors)
        self.assertEqual(self.rt.status('first')['state'], 'running')
        self.assertEqual(self.rt.status('second')['state'], 'running')
        self.rt.uninstall_component('second')
        self.installer.configure([spec])
        self.assertFalse(self.installer.pending)
        self.assertIn('second', self.rt.removed_installations())
        self.assertEqual(len(self.installer.control.sources()), 1)

    def test_bundled_catalog_refreshes_when_targets_already_installed(self):
        spec, _ = self.plugin('installed')
        spec['bundledDirectory'] = 'fixture'
        self.installer.configure([spec])
        self.settle()
        source, = self.installer.control.sources()
        before = self.rt.status('installed')
        index = Path(spec['location']) / 'polaris-source.json'
        value = json.loads(index.read_text())
        value['name'] = 'Updated catalog'
        index.write_text(json.dumps(value))
        self.installer.configure([spec])
        self.settle()
        updated, = self.installer.control.sources()
        self.assertNotEqual(updated['revision'], source['revision'])
        self.assertEqual(updated['name'], 'Updated catalog')
        self.assertEqual(self.rt.status('installed')['installation'], before['installation'])
        self.assertEqual(self.rt.status('installed')['instance'], before['instance'])
        self.assertTrue(self.installer.rows([updated])[0]['defaultCatalog'])

    def test_remote_default_fetches_even_when_installed_and_archives_only_after_success(self):
        import subprocess
        from unittest.mock import patch
        from components.sources import Sources
        legacy, _ = self.plugin('existing')
        repo = Path(legacy['location'])
        def git(*args):
            subprocess.run(['git','-C',str(repo),*args], check=True, capture_output=True)
        git('init'); git('config','user.name','Fixture'); git('config','user.email','test@example.invalid')
        git('add','.'); git('commit','-m','fixture')
        self.installer.configure([legacy]); self.settle()
        old, = self.installer.control.sources()
        before = self.rt.status('existing')['installation']
        origin = self.installer.control.installation_origin('existing')
        url = 'https://example.invalid/catalog.git'
        spec = dict(name='Remote', location=url, ref='HEAD', defaultCatalog=True,
                    components=[{'component':'existing'}],
                    migrateLegacy={'migration':'fixture-v1', 'remoteLocations':[]})
        run = Sources._git
        def transport(*args):
            return run(*(str(repo) if arg == url else arg for arg in args))
        with patch.object(Sources, '_git', side_effect=RuntimeError('offline')):
            self.installer.configure([spec]); self.settle()
        rows = self.installer.control.sources()
        self.assertFalse(next(r for r in rows if r['id'] == old['id']).get('archived', False))
        remote = next(r for r in rows if r['location'] == url)
        self.assertIsNone(remote['revision'])
        from components.manager import ManagerBridge
        bridge = ManagerBridge(self.rt)
        bridge.defaults = self.installer
        with patch.object(Sources, '_git', side_effect=transport):
            bridge.retryDefault(remote['id']); self.settle()
        rows = self.installer.control.sources()
        self.assertTrue(next(r for r in rows if r['id'] == old['id'])['archived'])
        remote = next(r for r in rows if r['location'] == url)
        self.assertIsNotNone(remote['revision'])
        self.assertEqual(self.rt.status('existing')['installation'], before)
        self.assertEqual(self.installer.control.installation_origin('existing'), origin)
        self.assertEqual(len(self.installer.control.catalog()), 1)
        self.assertEqual(len(self.installer.control.catalog(old['id'])), 1)
        future, _ = self.plugin('future')
        future_source = self.installer.control.add(future['location'])
        self.installer.configure([spec]); self.settle()
        future_row = next(r for r in self.installer.control.sources() if r['id'] == future_source['id'])
        self.assertFalse(future_row.get('archived', False))

    def test_distribution_presets(self):
        spec, = configured_sources({})
        self.assertEqual(spec['location'], 'https://github.com/gonerain/Polaris-desktop.git')
        self.assertEqual(spec['ref'], 'codex/marketplace-catalog')
        self.assertTrue(spec['defaultCatalog'])
        self.assertNotIn('bundledDirectory', spec)
        self.assertEqual({entry['component'] for entry in spec['components']},
                         {'org.polaris.agent', 'org.polaris.weixin', 'org.polaris.schedule'})
        self.assertEqual(configured_sources({'defaultSources': []}), [])
