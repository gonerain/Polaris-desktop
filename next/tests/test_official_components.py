"""Check the catalog against shipped declarations, without external installations."""
import json
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

from components.assistant import Assistant

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / 'official-components.json').read_text(encoding='utf-8'))


class OfficialComponentCatalogTests(unittest.TestCase):
    def test_bundled_manifest_identity_and_policy(self):
        rows = CATALOG['components']
        self.assertEqual(len(rows), len({row['id'] for row in rows}))
        bundled = {row['id']: row for row in rows if row['manifest']}
        manifests = {p.parent.name: p for p in (ROOT / 'components').glob('*/manifest.json')}
        self.assertEqual(set(bundled), set(manifests))
        for identity, path in manifests.items():
            with self.subTest(component=identity):
                row = bundled[identity]
                manifest = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(row['id'], manifest['id'])
                self.assertEqual(row['version'], manifest['version'])
                self.assertEqual(row['platformApi'], manifest['platformApi'])
                self.assertEqual(row['factory'], manifest['entry']['factory'])
                self.assertEqual(row['instancePolicy'], manifest.get('instances', {}).get('mode', 'single') + ' (default)')

    def test_assistant_contract_matches_real_description(self):
        row = next(row for row in CATALOG['components'] if row['id'] == 'assistant')
        description = Assistant().describe()
        for group in ('operations', 'events'):
            declared = {name: meta['provides'] for name, meta in description[group].items() if 'provides' in meta}
            self.assertEqual(row['provides'][group], declared)
        self.assertEqual(description['operations']['status']['access'], 'read')
        self.assertEqual(description['operations']['reply']['access'], 'write')
        self.assertEqual([view['id'] for view in description['views']], ['main'])

    def test_canvas_contract_matches_real_description(self):
        if importlib.util.find_spec('PySide6') is None:
            self.skipTest('Optional PySide6 is not installed')
        row = next(row for row in CATALOG['components'] if row['id'] == 'canvas')
        script = """
import json, tempfile
from PySide6.QtGui import QGuiApplication
from components.canvas import Canvas
app = QGuiApplication([])
with tempfile.TemporaryDirectory() as directory:
    description = Canvas(data_dir=directory).describe()
    print(json.dumps({group: {name: metadata['provides'] for name, metadata in description[group].items()
                              if 'provides' in metadata} for group in ('operations', 'events')}))
"""
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
        result = subprocess.run([sys.executable, '-c', script], env=env, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), row['provides'])

    def test_feishu_bot_manifest_and_capabilities(self):
        import tempfile
        from importlib import import_module
        source = ROOT / 'plugins' / 'feishu'
        row = next(item for item in CATALOG['components'] if item['id'] == 'org.polaris.feishu-bot')
        manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['id'], manifest['version'], manifest['entry']['factory']),
                         (row['id'], row['version'], row['factory']))
        self.assertEqual(manifest['instances']['mode'], row['instancePolicy'])
        sys.path.insert(0, str(source))
        self.addCleanup(sys.path.remove, str(source))
        with tempfile.TemporaryDirectory() as directory:
            component = import_module('polaris_feishu_bot').FeishuBot(
                {'instanceId': 'test-instance', 'dataDir': directory})
            description = component.describe()
        for group in ('operations', 'events'):
            declared = {name: meta['provides'] for name, meta in description[group].items() if 'provides' in meta}
            self.assertEqual(row['provides'][group], declared)

    def test_declared_contracts_have_explicit_major_version(self):
        for row in CATALOG['components']:
            for group in ('operations', 'events'):
                for contract in row['provides'][group].values():
                    with self.subTest(component=row['id'], contract=contract):
                        self.assertRegex(contract, r'^[a-z][a-z0-9_.-]*@[1-9][0-9]*$')

    def test_default_external_sources_are_catalogued(self):
        sources = json.loads((ROOT / 'components/manager/default-sources.json').read_text(encoding='utf-8'))
        rows = {row['id']: row for row in CATALOG['components']}
        for source in sources:
            self.assertEqual(rows[source['component']]['source'], source['location'])


if __name__ == '__main__':
    unittest.main()
