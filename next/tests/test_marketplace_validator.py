import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MarketplaceValidatorTests(unittest.TestCase):
    def test_explicit_base_checks_package_content_not_presentation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ('next/polaris_platform', 'next/components/sources'):
                shutil.copytree(ROOT / relative, root / relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (root / 'next/components/__init__.py').touch()
            (root / 'tools').mkdir()
            shutil.copy(ROOT / 'tools/validate_marketplace.py', root / 'tools')
            package = root / 'marketplace/packages/app'
            package.mkdir(parents=True)
            (package / 'Main.qml').write_text('import QtQuick\nItem {}')
            manifest = {'id':'example.app', 'name':'Example', 'version':'1',
                        'entry':{'adapter':'qt-quick','file':'Main.qml'}, 'requires':{}}
            manifest_path = package / 'polaris-application.json'
            manifest_path.write_text(json.dumps(manifest))
            asset = root / 'marketplace/icon.png'
            asset.write_bytes(b'icon')
            index = {'schemaVersion':2, 'name':'Fixture', 'packages':[{'type':'application',
                     'path':'packages/app','summary':'Example','author':'Author','icon':'icon.png'}]}
            (root / 'marketplace/polaris-source.json').write_text(json.dumps(index))
            def git(*args):
                return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True)
            git('init'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
            git('add','.'); git('commit','-m','base')
            def validate(base='HEAD'):
                return subprocess.run([sys.executable, 'tools/validate_marketplace.py', '--base', base],
                                      cwd=root, capture_output=True, text=True)
            asset.write_bytes(b'new presentation')
            self.assertEqual(validate().returncode, 0)
            (package / 'Main.qml').write_text('import QtQuick\nItem { width: 5 }')
            result = validate()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('without a version change', result.stderr + result.stdout)
            manifest['version'] = '2'
            manifest_path.write_text(json.dumps(manifest))
            self.assertEqual(validate().returncode, 0)
            asset.unlink()
            self.assertNotEqual(validate().returncode, 0)
            self.assertNotEqual(validate('not-a-real-base').returncode, 0)


if __name__ == '__main__':
    unittest.main()
