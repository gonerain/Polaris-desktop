import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from copy import deepcopy

from polaris_platform.bootstrap import build, default_config
from polaris_platform.protocol import PlatformError
from polaris_platform.runtime import _active
from polaris_platform.sources import Sources


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = self.root / 'repo'
        self.repository.mkdir()
        self.runtime = build(default_config(), state_dir=self.root / 'runtime')
        self.sources = Sources(self.runtime, self.root / 'state')
        self.runtime.install(dict(id='sources', name='Sources', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), lambda: self.sources)
        self.runtime.start_component('sources')
        self.control = self.sources.local_source_control()
        self.git('init')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.plugin('one')
        self.plugin('two')
        self.index()
        self.commit()
        self.addCleanup(self.modules)
        self.addCleanup(self.stop)

    def stop(self):
        for row in reversed(self.runtime.snapshot()):
            if row['state'] == 'running':
                self.runtime.stop_component(row['id'], persist=False)

    def test_stopped_and_restarted_source_rejects_old_controls(self):
        source = self.control.add(str(self.repository))
        install = self.control.install
        catalog = self.control.catalog
        self.runtime.stop_component('sources')
        for operation in (self.sources.local_source_control, lambda: install(source['id'], 'one'),
                          lambda: catalog(source['id']), lambda: self.control.preset({'name': 'new', 'location': 'unused'}),
                          lambda: self.control.fetch_preset(source['id'], lambda: False)):
            with self.assertRaises(PlatformError) as error:
                operation()
            self.assertEqual(error.exception.code, 'unavailable')
        self.runtime.start_component('sources')
        with self.assertRaises(PlatformError) as error:
            install(source['id'], 'one')
        self.assertEqual(error.exception.code, 'stale_instance')
        self.assertFalse(any(row['id'] == 'one' for row in self.runtime.snapshot()))
        self.sources.local_source_control().install(source['id'], 'one')
        self.assertEqual(self.runtime.status('one')['state'], 'installed')

    def test_fetch_in_flight_cannot_commit_after_source_restart(self):
        source_id = self.control.preset(dict(name='Fixture', location=str(self.repository)))
        prepared, finish = threading.Event(), threading.Event()
        prepare = self.sources._prepare
        fetched, errors = [], []
        def pause(*args):
            result = prepare(*args)
            fetched.append(result)
            prepared.set()
            if not finish.wait(5):
                raise TimeoutError('Test did not release the fetch')
            return result
        def fetch():
            try:
                self.control.fetch_preset(source_id, lambda: False)
            except Exception as error:
                errors.append(error)
        with patch.object(self.sources, '_prepare', side_effect=pause):
            worker = threading.Thread(target=fetch)
            worker.start()
            try:
                self.assertTrue(prepared.wait(5))
                self.runtime.stop_component('sources')
                self.runtime.start_component('sources')
            finally:
                finish.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        source, = self.sources.local_source_control().sources()
        self.assertIsNone(source['revision'])
        self.assertFalse(Path(fetched[0]['directory']).exists())
        saved = json.loads(self.sources._storage.read_text())
        self.assertIsNone(saved['sources'][source_id]['revision'])

    def modules(self):
        for name in list(sys.modules):
            if name.startswith('source_test_'):
                del sys.modules[name]

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repository), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-m', 'fixture')

    def index(self, components=None):
        (self.repository / 'polaris-source.json').write_text(json.dumps(dict(schemaVersion=1, name='Fixture', components=components or [{'path': 'one'}, {'path': 'two'}])))

    def plugin(self, name, version='1', fail=False):
        directory = self.repository / name
        directory.mkdir(exist_ok=True)
        (directory / 'manifest.json').write_text(json.dumps(dict(id=name, name=name, version=version, platformApi=1,
            entry=dict(mode='inprocess', factory=f'source_test_{name}:create'))))
        (directory / f'source_test_{name}.py').write_text('from polaris_platform.component import Component\ndef create():\n' +
            (' raise RuntimeError("broken plugin")\n' if fail else f' c=Component()\n c.operation("value")(lambda p,c: "{version}")\n return c\n'))

    def test_multi_plugin_commit_update_rollback_and_restart_records(self):
        source = self.control.add(str(self.repository))
        self.assertEqual(len(self.control.catalog(source['id'])), 2)
        self.control.install(source['id'], 'one')
        self.runtime.start_component('one')
        self.runtime.grant('runtime', 'one', 'value')
        before = self.runtime.status('one')
        grants = self.runtime.authorization.export_records()
        self.plugin('one', '2')
        self.commit()
        self.control.refresh(source['id'])
        self.control.update('one')
        self.assertEqual(self.runtime.status('one')['manifest']['version'], '2')
        self.assertEqual(self.runtime.status('one')['installation'], before['installation'])
        self.assertEqual(self.runtime.authorization.export_records(), grants)
        self.control.rollback('one')
        self.assertEqual(self.runtime.status('one')['manifest']['version'], '1')
        self.assertEqual(self.runtime.status('one')['state'], 'running')
        restored = Sources(self.runtime, self.root / 'state')
        self.assertEqual(restored.sources(), self.sources.sources())
        self.assertTrue(restored._data['installations']['one']['revision'])

    def test_failed_update_restores_running_old_code_and_source_record(self):
        source = self.control.add(str(self.repository))
        old = self.control.install(source['id'], 'one')
        self.runtime.start_component('one')
        self.plugin('one', '2', fail=True)
        self.commit()
        self.control.refresh(source['id'])
        with self.assertRaisesRegex(RuntimeError, 'broken plugin'):
            self.control.update('one')
        self.assertEqual(self.runtime.status('one')['state'], 'running')
        self.assertEqual(self.runtime.status('one')['manifest']['version'], '1')
        self.assertEqual(self.sources._data['installations']['one'], old)

    def test_unchanged_refresh_update_and_replace_preserve_instance_and_history(self):
        source = self.control.add(str(self.repository))
        installed = self.control.install(source['id'], 'one')
        self.runtime.start_component('one')
        instance = self.runtime.status('one')['instance']
        snapshots = set((self.sources._root / 'revisions').iterdir())
        for _ in range(2):
            refreshed = self.control.refresh(source['id'])
            self.assertEqual(refreshed['directory'], source['directory'])
            self.assertEqual(self.control.update('one'), installed)
            self.assertEqual(self.control.install(source['id'], 'one', replace=True), installed)
        self.assertEqual(self.runtime.status('one')['instance'], instance)
        self.assertEqual(set((self.sources._root / 'revisions').iterdir()), snapshots)

    def test_non_head_branch_and_tag_selection_for_local_and_remote(self):
        head = self.git('branch', '--show-current')
        self.git('checkout', '-b', 'release')
        self.plugin('one', '2')
        self.commit()
        revision = self.git('rev-parse', 'HEAD')
        self.git('tag', 'v2')
        self.git('checkout', head)
        branch = self.control.add(str(self.repository), ref='release')
        self.assertEqual(branch['revision'], revision)
        tag = self.control.add(str(self.repository), ref='v2')
        self.assertEqual(tag['revision'], revision)
        run_git = Sources._git
        def local_transport(*args):
            args = tuple(str(self.repository) if a == 'https://example.invalid/plugins.git' else a for a in args)
            return run_git(*args)
        with patch.object(Sources, '_git', side_effect=local_transport):
            remote = self.control.add('https://example.invalid/plugins.git', ref='release')
        self.assertEqual(remote['revision'], revision)

    def test_persistence_failure_restores_memory_runtime_and_saved_records(self):
        source = self.control.add(str(self.repository))
        before = deepcopy(self.sources._data)
        with patch.object(self.sources, '_save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.control.install(source['id'], 'one')
        self.assertEqual(self.sources._data, before)
        self.assertFalse(any(r['manifest']['id'] == 'one' for r in self.runtime.export_installations()))
        self.control.install(source['id'], 'one')
        self.runtime.start_component('one')
        self.plugin('one', '2')
        self.commit()
        self.control.refresh(source['id'])
        before = deepcopy(self.sources._data)
        with patch.object(self.sources, '_save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.control.update('one')
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.control.refresh(source['id'])
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.control.add(str(self.repository))
        self.assertEqual(self.sources._data, before)
        self.assertEqual(self.runtime.status('one')['manifest']['version'], '1')
        self.assertEqual(self.runtime.status('one')['state'], 'running')
        self.assertEqual(Sources(self.runtime, self.root / 'state')._data, before)

    def test_confirmed_replacement_keeps_rollback_and_checks_revision(self):
        source = self.control.add(str(self.repository))
        self.control.install(source['id'], 'one')
        identity = self.runtime.status('one')['installation']
        self.plugin('one', '2')
        self.commit()
        refreshed = self.control.refresh(source['id'])
        with self.assertRaises(PlatformError) as error:
            self.control.install(source['id'], 'one', replace=True, expected_revision=source['revision'])
        self.assertEqual(error.exception.code, 'source_changed')
        self.control.install(source['id'], 'one', replace=True, expected_installation=identity, expected_revision=refreshed['revision'])
        self.control.rollback('one')
        self.assertEqual(self.runtime.status('one')['manifest']['version'], '1')

    def test_external_reinstallation_does_not_inherit_source_record(self):
        source = self.control.add(str(self.repository))
        self.control.install(source['id'], 'one')
        origin = self.control.installation_origin('one')
        self.assertEqual(origin['sourceId'], source['id'])
        self.assertEqual(origin['revision'], source['revision'])
        self.runtime.uninstall_component('one')
        self.runtime.install_directory(self.repository / 'one')
        self.assertIsNone(self.control.installation_origin('one'))
        with self.assertRaises(PlatformError) as error:
            self.control.update('one')
        self.assertEqual(error.exception.code, 'installation_changed')

    def test_index_only_never_imports_code(self):
        self.plugin('one', fail=True)
        self.commit()
        source = self.control.add(str(self.repository))
        self.assertEqual(len(self.sources.catalog(source['id'])), 2)
        self.assertNotIn('source_test_one', sys.modules)

    def test_paths_duplicates_and_api_are_rejected(self):
        for components in [[{'path': '../outside'}], [{'path': '/tmp'}], [{'path': 'one'}, {'path': 'one'}]]:
            self.index(components)
            self.commit()
            with self.assertRaises(PlatformError):
                self.control.add(str(self.repository))
        self.index([{'path': 'one'}])
        manifest = self.repository / 'one' / 'manifest.json'
        data = json.loads(manifest.read_text())
        data['platformApi'] = 2
        manifest.write_text(json.dumps(data))
        self.commit()
        with self.assertRaises(PlatformError):
            self.control.add(str(self.repository))

    def application(self, version='1'):
        directory = self.repository / 'app'
        directory.mkdir(exist_ok=True)
        (directory / 'Main.qml').write_text('import QtQuick\nItem {}')
        (directory / 'polaris-application.json').write_text(json.dumps(dict(
            id='example.app', name='Example', version=version,
            entry=dict(adapter='qt-quick', file='Main.qml'), requires={})))

    def test_application_catalog_snapshot_and_revision(self):
        self.application()
        (self.repository / 'polaris-source.json').write_text(json.dumps(dict(
            schemaVersion=1, name='Fixture', components=[{'path': 'one'}],
            applications=[{'path': 'app', 'description': 'Example application'}])))
        self.commit()
        source = self.control.add(str(self.repository))
        self.assertEqual(len(self.control.catalog(source['id'])), 1)
        row, = self.control.application_catalog(source['id'])
        self.assertEqual(row['manifest']['version'], '1')
        self.assertEqual(row['description'], 'Example application')
        path = Path(self.control.application_path(source['id'], 'example.app', source['revision']))
        self.application('2')
        self.commit()
        updated = self.control.refresh(source['id'])
        self.assertEqual(json.loads((path / 'polaris-application.json').read_text())['version'], '1')
        self.assertEqual(self.control.application_catalog(source['id'])[0]['manifest']['version'], '2')
        with self.assertRaises(PlatformError) as error:
            self.control.application_path(source['id'], 'example.app', source['revision'])
        self.assertEqual(error.exception.code, 'source_changed')
        self.assertNotEqual(path, Path(self.control.application_path(source['id'], 'example.app', updated['revision'])))

    def test_v2_packages_metadata_and_content_digests(self):
        self.application()
        assets = self.repository / 'assets'
        assets.mkdir()
        (assets / 'icon.png').write_bytes(b'icon')
        (assets / 'readme.md').write_text('details')
        index = self.repository / 'polaris-source.json'
        entries = [dict(type='component', path='one', summary='One', author='Author', icon='assets/icon.png', tags=['tools']),
                   dict(type='application', path='app', summary='App', author='Author', icon='assets/icon.png', readme='assets/readme.md')]
        def save():
            index.write_text(json.dumps(dict(schemaVersion=2, name='Mixed', packages=entries)))
            self.commit()
        save()
        source = self.control.add(str(self.repository))
        rows = self.control.packages(source['id'])
        self.assertEqual({r['type'] for r in rows}, {'component', 'application'})
        component = next(r for r in rows if r['type'] == 'component')
        app = next(r for r in rows if r['type'] == 'application')
        installed = self.control.install(source['id'], 'one')
        self.runtime.start_component('one')
        instance = self.runtime.status('one')['instance']
        self.assertEqual(self.control.installation_origin('one')['contentDigest'], component['contentDigest'])
        entries[0]['summary'] = 'Changed presentation'
        (assets / 'icon.png').write_bytes(b'new icon')
        save()
        updated = self.control.refresh(source['id'])
        rows = self.control.packages(source['id'])
        self.assertEqual(next(r for r in rows if r['type'] == 'component')['contentDigest'], component['contentDigest'])
        self.assertEqual(next(r for r in rows if r['type'] == 'application')['contentDigest'], app['contentDigest'])
        self.assertEqual(self.control.update('one'), installed)
        self.assertEqual(self.runtime.status('one')['instance'], instance)
        self.plugin('one', '2')
        save()
        self.control.refresh(source['id'])
        self.assertNotEqual(self.control.catalog(source['id'])[0]['contentDigest'], component['contentDigest'])
        self.control.update('one')
        self.assertEqual(self.runtime.status('one')['manifest']['version'], '2')
        self.control.rollback('one')
        self.assertEqual(self.control.installation_origin('one')['contentDigest'], component['contentDigest'])

    def test_component_digest_tracks_linked_directory_contents(self):
        shared = self.repository / 'shared'
        shared.mkdir()
        (shared / 'helper.py').write_text('VALUE = 1\n')
        (self.repository / 'one' / 'shared').symlink_to('../shared', target_is_directory=True)
        self.commit()
        source = self.control.add(str(self.repository))
        before = self.control.catalog(source['id'])[0]['contentDigest']
        (shared / 'helper.py').write_text('VALUE = 2\n')
        self.commit()
        self.control.refresh(source['id'])
        self.assertNotEqual(self.control.catalog(source['id'])[0]['contentDigest'], before)

    def test_v1_display_document_must_stay_in_source(self):
        index = self.repository / 'polaris-source.json'
        index.write_text(json.dumps(dict(schemaVersion=1, name='Fixture',
                                        components=[{'path':'one', 'readme':'../outside'}])))
        self.commit()
        with self.assertRaises(PlatformError):
            self.control.add(str(self.repository))

    def test_v2_rejects_invalid_fields_and_assets(self):
        index = self.repository / 'polaris-source.json'
        asset = self.repository / 'icon.png'
        asset.write_bytes(b'icon')
        valid = dict(type='component', path='one', summary='One', author='Author', icon='icon.png')
        for change in ({'author': ''}, {'icon': '../outside'}, {'icon': 'one/manifest.json'},
                       {'screenshots': ['missing.png']}, {'tags': [3]}, {'type': 'other'}):
            entry = dict(valid, **change)
            index.write_text(json.dumps(dict(schemaVersion=2, name='Fixture', packages=[entry])))
            self.commit()
            with self.assertRaises(PlatformError):
                self.control.add(str(self.repository))

    def test_application_only_source_and_invalid_entries(self):
        self.application()
        index = self.repository / 'polaris-source.json'
        def write(entries):
            index.write_text(json.dumps(dict(schemaVersion=1, name='Apps', applications=entries)))
            self.commit()
        write([{'path': 'app'}])
        source = self.control.add(str(self.repository))
        self.assertEqual(self.control.catalog(source['id']), [])
        self.assertEqual(len(self.control.application_catalog(source['id'])), 1)
        for entries in ([{'path': '../outside'}], [{'path': 'app'}, {'path': 'app'}],
                        [{'path': 'app', 'description': 3}]):
            write(entries)
            with self.assertRaises(PlatformError):
                self.control.add(str(self.repository))
        (self.repository / 'app' / 'Main.qml').unlink()
        write([{'path': 'app'}])
        with self.assertRaises(PlatformError):
            self.control.add(str(self.repository))

    def test_archived_catalogs_remain_readable_and_archive_rolls_back_on_save_failure(self):
        self.application()
        (self.repository / 'polaris-source.json').write_text(json.dumps(dict(
            schemaVersion=1, name='Fixture', components=[{'path':'one'}], applications=[{'path':'app'}])))
        self.commit()
        source = self.control.add(str(self.repository))
        installed = self.control.install(source['id'], 'one')
        before = deepcopy(self.sources._data)
        with patch.object(self.sources, '_save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.control.archive_sources([source['id']], 'migration')
        self.assertEqual(self.sources._data, before)
        self.assertEqual(Sources(self.runtime, self.root / 'state')._data, before)
        self.control.archive_sources([source['id']], 'migration')
        self.assertEqual(self.control.catalog(), [])
        self.assertEqual(self.control.application_catalog(), [])
        self.assertEqual(self.control.packages(), [])
        self.assertEqual(len(self.control.catalog(source['id'])), 1)
        self.assertEqual(len(self.control.application_catalog(source['id'])), 1)
        self.assertEqual(len(self.control.packages(source['id'])), 2)
        self.assertEqual(self.control.installation_origin('one')['installationId'], installed['installationId'])
        new_source = self.control.add(str(self.repository))
        self.control.archive_sources([new_source['id']], 'migration')
        self.assertFalse(next(row for row in self.control.sources() if row['id'] == new_source['id']).get('archived', False))

    def test_local_symlink_escape_and_active_request_denied(self):
        plain = self.root / 'plain'
        plain.mkdir()
        link = plain / 'escape'
        try:
            link.symlink_to(self.repository, target_is_directory=True)
        except OSError as error:
            if getattr(error, 'winerror', None) != 1314:
                raise
            # Windows without symlink privileges still supports directory junctions.
            import _winapi
            _winapi.CreateJunction(str(self.repository), str(link))
        with self.assertRaises(PlatformError):
            self.control.add(str(plain))
        token = _active.set(object())
        try:
            with self.assertRaises(PlatformError):
                self.control.add(str(self.repository))
        finally:
            _active.reset(token)

    def test_existing_install_requires_explicit_replacement_and_identity(self):
        self.runtime.install_directory(self.repository / 'one')
        installation = self.runtime.status('one')['installation']
        source = self.control.add(str(self.repository))
        with self.assertRaises(PlatformError):
            self.control.install(source['id'], 'one')
        with self.assertRaises(PlatformError):
            self.control.install(source['id'], 'one', replace=True, expected_installation='stale')
        self.control.install(source['id'], 'one', replace=True, expected_installation=installation)
        self.assertEqual(self.runtime.status('one')['installation'], installation)


if __name__ == '__main__':
    unittest.main()
