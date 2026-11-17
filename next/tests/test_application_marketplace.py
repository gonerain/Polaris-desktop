import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class ApplicationMarketplaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qt = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        from polaris_platform.bootstrap import build, default_config
        from polaris_platform.component import Component
        from polaris_platform.desktop.application_host import ApplicationHost
        from polaris_platform.sources import Sources
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.package('1')
        (self.repo / 'polaris-source.json').write_text(json.dumps({
            'schemaVersion': 1, 'name': 'Fixture', 'applications': [{'path': 'app'}]}))
        self.commit()
        self.runtime = build(default_config(), state_dir=self.root / 'runtime')
        component = Component()
        component.operation('echo', applicationBinding='instance')(lambda p, c: p)
        self.runtime.install(dict(id='provider', name='Provider', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), lambda: component)
        self.runtime.start_component('provider')
        self.sources = Sources(self.runtime, self.root / 'source-state')
        self.runtime.install(dict(id='sources', name='Sources', version='1', platformApi=1,
                                  entry=dict(mode='inprocess')), lambda: self.sources)
        self.runtime.start_component('sources')
        self.control = self.sources.local_source_control()
        self.source = self.control.add(str(self.repo))
        self.host = ApplicationHost(self.runtime)
        self.host.configure(self.root / 'desktop')
        self.path_patch = patch('polaris_platform.desktop.application_host.ManagementControlPort.application_path',
                                lambda port, source, package, revision: self.control.application_path(source, package, revision))
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.host.close()
        for row in reversed(self.runtime.snapshot()):
            if row['state'] == 'running':
                self.runtime.stop_component(row['id'], persist=False)
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-m', 'fixture')

    def package(self, version, package_id='example.app'):
        directory = self.repo / 'app'
        directory.mkdir(exist_ok=True)
        (directory / 'Main.qml').write_text('import QtQuick\nItem {}')
        (directory / 'polaris-application.json').write_text(json.dumps(dict(
            id=package_id, name='Example', version=version,
            entry=dict(adapter='qt-quick', file='Main.qml'),
            requires={'echo': dict(componentType='provider', operation='echo', major=1, access='read')})))

    def install(self):
        identity = self.host.installSourceApplication(self.source['id'], 'example.app', self.source['revision'])
        self.assertTrue(identity, self.host.error)
        return identity

    def rows(self):
        return json.loads(self.host.managedApplicationsJson)

    def test_revision_selection_update_and_local_update(self):
        from polaris_platform.application import Application
        foreground = Application('Foreground')
        self.host.importJson(json.dumps(foreground.as_dict()))
        self.assertEqual(self.runtime.status(foreground.id)['state'], 'running')
        identity = self.install()
        selected = foreground.id
        self.assertEqual(self.host._selected, selected)
        app = self.host.store.load(identity)
        app.config = {'key': 'value'}
        stable = self.runtime.status('provider')['instanceId']
        client = self.runtime.client('provider')
        app.bindings = {'echo': dict(target=stable, installationId=stable, instanceId=stable,
                                     operation='echo', semantic=list(client.bind(stable, 'echo').semantic))}
        self.host.store.save(app)
        self.runtime.register_application_bindings(identity, [stable])
        self.runtime.grant(identity, stable, 'echo')
        self.assertTrue(self.runtime.authorization.scope(identity))
        grants = self.runtime.authorization.export_records()
        self.package('2')
        self.commit()
        current = self.control.refresh(self.source['id'])
        origin = self.host._source_origins[identity].copy()
        self.host.updateSourceApplication(identity, self.source['id'], 'example.app', self.source['revision'])
        self.assertIn('revision changed', self.host.error)
        self.assertEqual(self.host._source_origins[identity], origin)
        self.host.updateSourceApplication(identity, self.source['id'], 'example.app', current['revision'])
        self.assertFalse(self.host.error, self.host.error)
        updated = self.host.store.load(identity)
        self.assertEqual(updated.config, app.config)
        self.assertEqual(updated.bindings, app.bindings)
        self.assertEqual(self.runtime.authorization.export_records(), grants)
        self.runtime.start_application(identity)
        result = self.runtime.application_client(identity).call(
            stable, 'echo', {'text': 'retained'}, self.runtime.application_context(identity))
        self.assertEqual(result, {'text': 'retained'})
        self.assertEqual(self.runtime.status('provider')['instanceId'], stable)
        self.assertEqual(self.runtime.status('provider')['state'], 'running')
        self.assertEqual(self.host._selected, selected)
        self.assertEqual(self.runtime.status(selected)['state'], 'running')
        self.assertEqual(self.host.packages.load_verified(updated)['manifest']['version'], '2')
        self.assertEqual(self.host._source_origins[identity]['revision'], current['revision'])
        self.host.close()
        self.host.configure(self.root / 'desktop')
        self.host.refreshManagedApplications()
        self.assertEqual(next(r for r in self.rows() if r['applicationId'] == identity)['origin']['revision'], current['revision'])
        self.host.updateApplication(identity, str(self.repo / 'app'))
        self.assertFalse(self.host.error, self.host.error)
        self.assertNotIn(identity, self.host._source_origins)
        self.assertNotIn('origin', next(r for r in self.rows() if r['applicationId'] == identity))

    def test_failed_update_and_source_record_write_restore_state(self):
        identity = self.install()
        before = self.host.store.load(identity).as_dict()
        origin = self.host._source_origins[identity].copy()
        self.package('2')
        self.commit()
        current = self.control.refresh(self.source['id'])
        with patch('polaris_platform.desktop.application_host.write_json', side_effect=OSError('disk full')):
            self.host.updateSourceApplication(identity, self.source['id'], 'example.app', current['revision'])
        self.assertIn('disk full', self.host.error)
        self.assertEqual(self.host.store.load(identity).as_dict(), before)
        self.assertEqual(self.host._source_origins[identity], origin)
        self.assertEqual(json.loads((self.root / 'desktop' / 'application-sources.json').read_text())[identity], origin)

    def test_async_backend_stop_commits_origin_only_after_success(self):
        from PySide6.QtTest import QTest
        identity = self.install()
        before = self.host.store.load(identity).as_dict()
        origin = self.host._source_origins[identity].copy()
        self.package('2')
        self.commit()
        current = self.control.refresh(self.source['id'])

        class Runner:
            def __init__(self, error):
                self.stopped = threading.Event()
                self.stop_error = error

        def wait_for_commit():
            for _ in range(600):
                self.qt.processEvents()
                if identity not in self.host._package_updates:
                    return
                QTest.qWait(5)
            self.fail('Application update did not finish')

        with patch.object(self.host, '_stop_application'):
            for failure in ('backend stop failed', ''):
                runner = Runner(failure)
                self.host._backends[identity] = runner
                self.host.updateSourceApplication(identity, self.source['id'], 'example.app', current['revision'])
                self.assertIn(identity, self.host._package_updates)
                self.assertEqual(self.host.store.load(identity).as_dict(), before)
                self.assertEqual(self.host._source_origins[identity], origin)
                runner.stopped.set()
                wait_for_commit()
                if failure:
                    self.assertIn(failure, self.host.error)
                    self.assertEqual(self.host.store.load(identity).as_dict(), before)
                    self.assertEqual(self.host._source_origins[identity], origin)
                else:
                    updated = self.host.store.load(identity)
                    stored = self.host._source_origins[identity]
                    self.assertEqual(stored['revision'], current['revision'])
                    self.assertEqual(stored['snapshot'], updated.package['snapshot'])
                    self.assertEqual(stored['digest'], updated.package['digest'])
                    self.assertNotEqual(updated.package['snapshot'], before['package']['snapshot'])

    def test_source_record_write_failure_keeps_install_and_removal_consistent(self):
        with patch('polaris_platform.desktop.application_host.write_json', side_effect=OSError('disk full')):
            identity = self.host.installSourceApplication(self.source['id'], 'example.app', self.source['revision'])
        self.assertEqual(identity, '')
        self.assertEqual(self.host._definitions(), [])
        identity = self.install()
        before = self.host.store.load(identity).as_dict()
        with patch('polaris_platform.desktop.application_host.write_json', side_effect=OSError('disk full')):
            self.host.removeApplication(identity)
        self.assertIn('disk full', self.host.error)
        self.assertEqual(self.host.store.load(identity).as_dict(), before)
        self.assertIn(identity, self.host._source_origins)

    def test_explicit_target_among_same_package_and_stale_origin(self):
        identity = self.install()
        other = self.host.packages.install(self.repo / 'app')
        self.host._ensure_application(other)
        self.runtime.register_application_bindings(other.id, [])
        self.host.store.save(other)
        self.host.refreshManagedApplications()
        self.assertEqual(len([r for r in self.rows() if r.get('packageId') == 'example.app']), 2)
        self.assertNotIn('origin', next(r for r in self.rows() if r['applicationId'] == other.id))
        self.package('2')
        self.commit()
        current = self.control.refresh(self.source['id'])
        self.host.updateSourceApplication(other.id, self.source['id'], 'example.app', current['revision'])
        self.assertFalse(self.host.error, self.host.error)
        self.assertEqual(self.host.packages.load_verified(self.host.store.load(identity))['manifest']['version'], '1')
        self.assertEqual(self.host.packages.load_verified(self.host.store.load(other.id))['manifest']['version'], '2')
        self.host._source_origins[identity]['snapshot'] = 'stale'
        self.host.refreshManagedApplications()
        self.assertNotIn('origin', next(r for r in self.rows() if r['applicationId'] == identity))
        self.host.removeApplication(other.id)
        self.assertNotIn(other.id, self.host._source_origins)
        self.assertIn(identity, self.host._source_origins)


if __name__ == '__main__':
    unittest.main()
