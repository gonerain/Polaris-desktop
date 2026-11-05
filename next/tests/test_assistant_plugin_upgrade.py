"""The legacy export upgrade is narrow, recoverable and preserves its identity."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('assistant_upgrade', ROOT / 'tools/upgrade_assistant_plugin.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class AssistantPluginUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.export = self.root / 'artifact/plugins/assistant'
        self.export.mkdir(parents=True)
        self.package = self.export / 'polaris_assistant'
        shutil.copytree(upgrade.CANONICAL, self.package, ignore=shutil.ignore_patterns('__pycache__'))
        self.manifest = dict(id='assistant', name='Polaris Agent', version='0.2.1', platformApi=1,
                             entry=dict(mode='inprocess', factory='polaris_assistant:create'))
        (self.export / 'manifest.json').write_text(json.dumps(self.manifest))
        self.backup = self.root / 'backup'

    def test_backup_identity_and_unrelated_source_files_are_preserved(self):
        sibling = self.export.parent / 'agent'
        sibling.mkdir()
        (sibling / 'sentinel').write_text('untouched')
        before = {p.name:p.read_bytes() for p in self.package.iterdir() if p.is_file()}
        receipt = upgrade.upgrade(self.export, self.backup)
        self.assertEqual(json.loads((self.export / 'manifest.json').read_text()), self.manifest)
        self.assertEqual((sibling / 'sentinel').read_text(), 'untouched')
        self.assertEqual(set(receipt['files']), {'Chat.qml','__init__.py','view.py','settings.py'})
        for name, contents in before.items():
            self.assertEqual((self.backup / 'polaris_assistant' / name).read_bytes(), contents)
            if name not in receipt['files']:
                self.assertEqual((self.package / name).read_bytes(), contents)

    def test_custom_business_or_wrong_factory_is_rejected_before_writes(self):
        original = (self.package / 'model.py').read_bytes()
        (self.package / 'model.py').write_text('# customized\n')
        with self.assertRaisesRegex(ValueError, 'customized'):
            upgrade.upgrade(self.export, self.backup)
        self.assertFalse(self.backup.exists())
        (self.package / 'model.py').write_bytes(original)
        self.manifest['entry']['factory'] = 'custom_assistant:create'
        (self.export / 'manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'official legacy'):
            upgrade.upgrade(self.export, self.backup)
        self.assertFalse(self.backup.exists())

    def test_partial_write_failure_restores_code_and_keeps_backup(self):
        original = {name:(self.package / name).read_bytes() for name in upgrade.FILES}
        real_replace = upgrade.os.replace
        writes = []
        def fail_second(source, target):
            writes.append(target)
            if len(writes) == 2:
                raise OSError('write failed')
            return real_replace(source, target)
        with patch.object(upgrade.os, 'replace', fail_second), self.assertRaises(OSError):
            upgrade.upgrade(self.export, self.backup)
        self.assertTrue(self.backup.is_dir())
        for name, contents in original.items():
            self.assertEqual((self.package / name).read_bytes(), contents)
