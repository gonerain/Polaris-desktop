import json
from pathlib import Path
import tempfile
import unittest

from polaris_platform.application import Application, ApplicationStore
from polaris_platform.application_package import ApplicationPackageStore
from polaris_platform.protocol import PlatformError


class ApplicationPackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.manifest = {'id': 'demo.echo', 'name': 'Echo', 'version': '1',
                         'entry': {'adapter': 'qt-quick', 'file': 'Main.qml'},
                         'requires': {'echo': {'componentType': 'demo.provider', 'operation': 'echo',
                                               'major': 1, 'access': 'read'}}}
        self.write_manifest()
        (self.source / 'Main.qml').write_text('import QtQuick\nItem {}\n')
        self.packages = ApplicationPackageStore(self.root / 'packages')

    def write_manifest(self):
        (self.source / 'polaris-application.json').write_text(json.dumps(self.manifest))

    def test_snapshot_identity_persistence_and_change_detection(self):
        first = self.packages.install(self.source)
        second = self.packages.install(self.source)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.bindings, {})
        store = ApplicationStore(self.root / 'definitions')
        store.save(first)
        loaded = store.load(first.id)
        result = self.packages.load_verified(loaded)
        self.assertEqual(result['manifest']['id'], 'demo.echo')
        self.assertEqual(result['requires'], self.manifest['requires'])
        (self.source / 'Main.qml').write_text('changed source')
        self.packages.load_verified(loaded)
        Path(result['entry']).write_text('changed installed snapshot')
        with self.assertRaises(PlatformError) as raised:
            self.packages.load_verified(loaded)
        self.assertEqual(raised.exception.code, 'application_package_changed')
        self.packages.remove(loaded)
        self.packages.load_verified(second)

    def test_rejects_escape_symlink_and_manifest_authority(self):
        for path in ('../Main.qml', '/tmp/Main.qml', 'sub/../Main.qml'):
            self.manifest['entry']['file'] = path
            self.write_manifest()
            with self.assertRaises(PlatformError):
                self.packages.install(self.source)
        self.manifest['entry']['file'] = 'Main.qml'
        self.manifest['applicationId'] = 'owned-by-developer'
        self.write_manifest()
        with self.assertRaises(PlatformError):
            self.packages.install(self.source)
        del self.manifest['applicationId']
        self.write_manifest()
        (self.source / 'escape').symlink_to(self.root)
        with self.assertRaises(PlatformError):
            self.packages.install(self.source)
        self.assertFalse(self.packages.directory.exists())

    def test_legacy_schema_roundtrip(self):
        app = Application('Legacy')
        self.assertEqual(Application.from_dict(app.as_dict()).as_dict(), app.as_dict())

    def test_rejects_store_inside_source_and_missing_schema2_package(self):
        nested = ApplicationPackageStore(self.source / 'packages')
        with self.assertRaises(PlatformError):
            nested.install(self.source)
        self.assertFalse(nested.directory.exists())
        value = Application('Legacy').as_dict()
        value.update(schemaVersion=2, package=None)
        with self.assertRaises(PlatformError):
            Application.from_dict(value)


if __name__ == '__main__':
    unittest.main()
