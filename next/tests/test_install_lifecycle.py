import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
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
