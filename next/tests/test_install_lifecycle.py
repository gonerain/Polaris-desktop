import json
import os
import shutil
from pathlib import Path
import tempfile
import sys
import threading
import unittest
from unittest.mock import patch
from polaris_platform.bootstrap import build, default_config, from_file
from polaris_platform.component import Component
from polaris_platform.protocol import PlatformError


class InstallationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = build(default_config(), state_dir=self.base / 'state')

    def tearDown(self):
        for name, module in list(sys.modules.items()):
            source = getattr(module, '__file__', None)
            if source and Path(source).resolve().is_relative_to(self.base):
                del sys.modules[name]

    def plugin(self, value='old', version='1'):
        directory = self.base / 'plugin'
        directory.mkdir(exist_ok=True)
        (directory / 'manifest.json').write_text(json.dumps(dict(id='plugin', name='Plugin', version=version,
            platformApi=1, entry=dict(mode='inprocess', factory='lifecycle_test_plugin:create'))))
        (directory / 'lifecycle_test_plugin.py').write_text(
            'from polaris_platform.component import Component\ndef create():\n c=Component()\n'
            f' c.operation("value")(lambda p,c: "{value}")\n return c\n')
        return directory

    def test_explicit_update_runs_new_source_preserves_identity_and_grants(self):
        r = self.runtime
        directory = self.plugin()
        r.install_directory(directory)
        r.start_component('plugin')
        r.grant('runtime', 'plugin', 'value')
        context = r.user_context('runtime')
        client = r.client('runtime')
        handle = client.bind('plugin', 'value')
        old = r.status('plugin')
        source = directory / 'lifecycle_test_plugin.py'
        timestamp = source.stat().st_mtime_ns
        self.plugin('new', '2')
        os.utime(source, ns=(timestamp, timestamp))
        with self.assertRaises(PlatformError) as failure:
            r.install_directory(directory)
        self.assertEqual(failure.exception.code, 'already_installed')
        r.install_directory(directory, replace=True)
        self.assertEqual(client.call('plugin', 'value', context=context), 'new')
        self.assertEqual(r.status('plugin')['installation'], old['installation'])
        with self.assertRaises(PlatformError) as failure:
            client.invoke(handle, context=context)
        self.assertEqual(failure.exception.code, 'stale_handle')
        restarted = build(default_config(), state_dir=self.base / 'state')
        self.assertEqual(restarted.status('plugin')['manifest']['version'], '2')

    def test_utf8_manifest_and_assembly_keep_non_ascii_names(self):
        directory = self.plugin()
        path = directory / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['name'] = '微信组件'
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        self.runtime.install_directory(directory)
        self.assertEqual(self.runtime.status('plugin')['manifest']['name'], '微信组件')
        config = default_config()
        config['components'].append({'directory': str(directory)})
        config['description'] = '中文装配配置'
        assembly = self.base / 'config.json'
        assembly.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        runtime = from_file(assembly)
        try:
            self.assertEqual(runtime.status('plugin')['manifest']['name'], '微信组件')
        finally:
            for record in reversed(runtime.snapshot()):
                if record['state'] == 'running':
                    runtime.stop_component(record['id'], persist=False)

    def test_uninstall_keeps_files_and_new_install_has_new_authority(self):
        r = self.runtime
        directory = self.plugin()
        r.install_directory(directory)
        r.start_component('plugin')
        r.grant('runtime', 'plugin', 'value')
        old = r.status('plugin')['installation']
        r.uninstall_component('plugin')
        self.assertTrue((directory / 'manifest.json').exists())
        config = default_config()
        config['components'].append({'directory': str(directory)})
        restarted = build(config, state_dir=self.base / 'state')
        self.assertNotIn('plugin', [row['id'] for row in restarted.snapshot()])
        r.install_directory(directory)
        r.start_component('plugin')
        self.assertNotEqual(old, r.status('plugin')['installation'])
        with self.assertRaises(PlatformError) as failure:
            r.client('runtime').call('plugin', 'value', context=r.user_context('runtime'))
        self.assertEqual(failure.exception.code, 'permission_required')

    def test_package_child_source_and_directory_switch(self):
        r = self.runtime
        directories = [self.base / name for name in ('a', 'b')]
        for directory, value in zip(directories, ('old', 'new')):
            package = directory / 'lifecycle_owned_package'
            package.mkdir(parents=True)
            (directory / 'manifest.json').write_text(json.dumps(dict(id='owned', name='Owned', version=value,
                platformApi=1, entry=dict(mode='inprocess', factory='lifecycle_owned_package:create'))))
            (package / '__init__.py').write_text('from polaris_platform.component import Component\ndef create():\n from .child import value\n c=Component()\n c.operation("value")(lambda p,c:value)\n return c\n')
            (package / 'child.py').write_text(f'value="{value}"\n')
        r.install_directory(directories[0])
        r.start_component('owned')
        r.grant('runtime', 'owned', 'value')
        client, context = r.client('runtime'), r.user_context('runtime')
        for directory, expected in ((directories[1], 'new'), (directories[0], 'old')):
            r.install_directory(directory, replace=True)
            self.assertEqual(client.call('owned', 'value', context=context), expected)
        source = directories[0] / 'lifecycle_owned_package' / 'child.py'
        timestamp = source.stat().st_mtime_ns
        source.write_text('value="upd"\n')
        os.utime(source, ns=(timestamp, timestamp))
        r.install_directory(directories[0], replace=True)
        self.assertEqual(client.call('owned', 'value', context=context), 'upd')
        r.uninstall_component('owned')
        source.write_text('value="end"\n')
        os.utime(source, ns=(timestamp, timestamp))
        r.install_directory(directories[0])
        r.start_component('owned')
        r.grant('runtime', 'owned', 'value')
        self.assertEqual(client.call('owned', 'value', context=r.user_context('runtime')), 'end')

    def test_uninstall_direct_install_without_source_directory(self):
        manifest = dict(id='direct', name='Direct', version='1', platformApi=1,
                        entry=dict(mode='inprocess', factory='direct_entry:create'))
        self.runtime.install(manifest, Component)
        self.runtime.start_component('direct')
        self.assertEqual(self.runtime.uninstall_component('direct')['state'], 'uninstalled')
        self.assertIn('direct', self.runtime.removed_installations())

    def test_stop_rejects_component_while_start_is_in_progress(self):
        entered, release = threading.Event(), threading.Event()
        errors = []

        class SlowStart(Component):
            def start(self, port):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('start was not released')
                super().start(port)

        manifest = dict(id='slow', name='Slow', version='1', platformApi=1,
                        entry=dict(mode='inprocess', factory='slow:create'))
        self.runtime.install(manifest, SlowStart)

        def start():
            try:
                self.runtime.start_component('slow')
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=start)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(PlatformError) as failure:
                self.runtime.stop_component('slow')
            self.assertEqual(failure.exception.code, 'busy')
            self.assertEqual(self.runtime.status('slow')['state'], 'starting')
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.runtime.status('slow')['state'], 'running')
        self.runtime.stop_component('slow')

    def test_uninstall_prevents_concurrent_restart_and_management(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        directory = self.plugin()
        self.runtime.install_directory(directory)
        self.runtime.start_component('plugin')
        old = self.runtime.component_instance('plugin')

        def pause(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('uninstall was not released')

        def uninstall():
            try:
                self.runtime.uninstall_component('plugin')
            except Exception as error:
                errors.append(error)

        with patch('polaris_platform.bootstrap.invalidate_plugin_modules', side_effect=pause):
            thread = threading.Thread(target=uninstall)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertIsNone(old.port)
                for action in (lambda: self.runtime.start_component('plugin'),
                               lambda: self.runtime.stop_component('plugin'),
                               lambda: self.runtime.uninstall_component('plugin')):
                    with self.assertRaises(PlatformError) as failure:
                        action()
                    self.assertEqual(failure.exception.code, 'busy')
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertNotIn('plugin', [row['id'] for row in self.runtime.snapshot()])

    def test_failed_install_persistence_leaves_no_record_or_identity(self):
        directory = self.plugin()
        with patch('polaris_platform.persistence.write_json', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.runtime.install_directory(directory)
        self.assertNotIn('plugin', [row['id'] for row in self.runtime.snapshot()])
        self.assertNotIn('plugin', self.runtime.authorization._identities)
        restarted = build(default_config(), state_dir=self.base / 'state')
        self.assertNotIn('plugin', [row['id'] for row in restarted.snapshot()])
        self.runtime.install_directory(directory)
        self.assertEqual(self.runtime.status('plugin')['state'], 'installed')

    def test_failed_reinstall_preserves_tombstone_on_restart(self):
        from polaris_platform.persistence import write_json
        directory = self.plugin()
        self.runtime.install_directory(directory)
        self.runtime.uninstall_component('plugin')
        writes = []

        def fail_second_write(path, value):
            writes.append(Path(path).name)
            if len(writes) == 2:
                raise OSError('disk full')
            write_json(path, value)

        with patch('polaris_platform.persistence.write_json', side_effect=fail_second_write):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.runtime.install_directory(directory)
        self.assertEqual(writes, ['installations.json', 'removed-installations.json'])
        self.assertIn('plugin', self.runtime.removed_installations())
        self.assertNotIn('plugin', [row['id'] for row in self.runtime.snapshot()])
        config = default_config()
        config['components'].append({'directory': str(directory)})
        # Bootstrap writes its own state, so use a snapshot to check the
        # immediate restart without altering the subsequent persist scenario.
        snapshot = self.base / 'restart-snapshot'
        shutil.copytree(self.base / 'state', snapshot)
        immediate = build(config, state_dir=snapshot)
        self.assertNotIn('plugin', [row['id'] for row in immediate.snapshot()])
        self.runtime._persist()
        restarted = build(config, state_dir=self.base / 'state')
        self.assertNotIn('plugin', [row['id'] for row in restarted.snapshot()])

    def test_uninstall_write_failures_keep_recoverable_state(self):
        from polaris_platform.persistence import write_json

        for fail_at in (1, 2, 3):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as state:
                directory = self.plugin()
                data = directory / 'user-data.txt'
                data.write_text('keep', encoding='utf-8')
                runtime = build(default_config(), state_dir=state)
                runtime.install_directory(directory)
                runtime.start_component('plugin')
                writes = []

                def fail_write(path, value):
                    writes.append(Path(path).name)
                    if len(writes) == fail_at:
                        raise OSError('disk full')
                    write_json(path, value)

                with patch('polaris_platform.persistence.write_json', side_effect=fail_write):
                    if fail_at < 3:
                        with self.assertRaisesRegex(OSError, 'disk full'):
                            runtime.uninstall_component('plugin')
                    else:
                        with self.assertLogs('components.runtime', level='WARNING'):
                            result = runtime.uninstall_component('plugin')
                        self.assertEqual(result['state'], 'uninstalled')
                self.assertEqual(data.read_text(encoding='utf-8'), 'keep')
                installed = 'plugin' in [row['id'] for row in runtime.snapshot()]
                self.assertEqual(installed, fail_at < 3)
                if installed:
                    self.assertEqual(runtime.status('plugin')['state'], 'stopped')
                config = default_config()
                config['components'].append({'directory': str(directory)})
                restarted = build(config, state_dir=state)
                self.assertEqual('plugin' in [row['id'] for row in restarted.snapshot()], fail_at < 3)
                if installed:
                    runtime.uninstall_component('plugin')
                    self.assertNotIn('plugin', [row['id'] for row in runtime.snapshot()])
                else:
                    runtime._persist()
                    again = build(config, state_dir=state)
                    self.assertNotIn('plugin', [row['id'] for row in again.snapshot()])

    def test_bootstrap_configuration_can_update_foundation(self):
        config = default_config()
        original = self.runtime.status('runtime')['installation']
        for item in config['components']:
            if item['manifest']['id'] == 'runtime':
                item['manifest']['version'] = '2'
        restarted = build(config, state_dir=self.base / 'state')
        self.assertEqual(restarted.status('runtime')['manifest']['version'], '2')
        self.assertEqual(restarted.status('runtime')['installation'], original)

    def test_failed_stop_preserves_installation_and_replacement_manifest(self):
        class RefusesStop(Component):
            def stop(self):
                raise PlatformError('stopping', 'Still busy')
        r = self.runtime
        directory = self.plugin()
        manifest = json.loads((directory / 'manifest.json').read_text())
        r.install(manifest, RefusesStop, directory=directory)
        r.start_component('plugin')
        self.plugin('new', '2')
        for action in (lambda: r.uninstall_component('plugin'), lambda: r.install_directory(directory, replace=True)):
            with self.assertRaises(PlatformError) as failure:
                action()
            self.assertEqual(failure.exception.code, 'stopping')
            self.assertEqual(r.status('plugin')['manifest']['version'], '1')
        for identity in r.roles.values():
            with self.assertRaises(PlatformError) as failure:
                r.uninstall_component(identity)
            self.assertEqual(failure.exception.code, 'restart_required')
