import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from polaris_platform.updates import check_release, download_release, parse_release, version_tuple


class UpdateTests(unittest.TestCase):
    payload = b'example deb package'

    def release(self, version='1.2.3.4', arch='amd64'):
        name = f'polaris_{version}_{arch}.deb'
        return {'tag_name': f'v{version}', 'assets': [{
            'name': name, 'size': len(self.payload),
            'browser_download_url': f'https://github.com/gonerain/Polaris-desktop/releases/download/v{version}/{name}',
            'digest': 'sha256:' + hashlib.sha256(self.payload).hexdigest(),
        }]}

    def parse(self, data):
        return parse_release(data, current='1.0.0.0', arch='amd64')

    def test_numeric_version_order_and_no_downgrade(self):
        self.assertGreater(version_tuple('v1.10.0'), version_tuple('v1.9.99'))
        self.assertEqual(version_tuple('v1.2.3'), version_tuple('1.2.3.0'))
        self.assertIsNone(self.parse(self.release('1.0.0.0')))
        self.assertIsNone(self.parse(self.release('0.9.0.0')))
        for invalid in ('main', 'v1.0.0-rc1', '../1.0.0', '', None):
            with self.assertRaises(ValueError): version_tuple(invalid)

    def test_only_stable_matching_architecture(self):
        data = self.release()
        data['prerelease'] = True
        self.assertIsNone(self.parse(data))
        with self.assertRaisesRegex(ValueError, '没有'):
            self.parse(self.release(arch='arm64'))
        self.assertEqual(self.parse(self.release()).version, '1.2.3.4')

    def test_requires_official_url_size_and_digest(self):
        for field, value in [('browser_download_url', 'https://example.com/evil.deb'),
                             ('digest', None), ('size', -1), ('size', True)]:
            data = self.release()
            data['assets'][0][field] = value
            with self.assertRaises(ValueError): self.parse(data)

    def test_no_release_is_explicit(self):
        with patch('polaris_platform.updates._open', side_effect=HTTPError('url', 404, 'missing', {}, None)):
            with self.assertRaisesRegex(ValueError, '尚无'): check_release()

    def test_verified_download_and_atomic_cleanup(self):
        release = self.parse(self.release())
        with tempfile.TemporaryDirectory() as folder:
            progress = []
            with patch('polaris_platform.updates._open', return_value=io.BytesIO(self.payload)):
                result = download_release(release, folder, progress.append)
            self.assertEqual(result.read_bytes(), self.payload)
            self.assertEqual(progress[-1], 100)
            for corrupt in (b'too short', b'x' * len(self.payload), self.payload + b'extra'):
                with patch('polaris_platform.updates._open', return_value=io.BytesIO(corrupt)):
                    with self.assertRaises(ValueError): download_release(release, folder)
                self.assertEqual(result.read_bytes(), self.payload)
                self.assertEqual(list(Path(folder).glob('*.part')), [])

    def test_network_failure_removes_partial_download(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('polaris_platform.updates._open', side_effect=TimeoutError('timeout')):
                with self.assertRaises(TimeoutError): download_release(self.parse(self.release()), folder)
            self.assertEqual(list(Path(folder).iterdir()), [])


class UpdateWindowTests(unittest.TestCase):
    def test_check_download_and_installer_fallback(self):
        import importlib.util
        if importlib.util.find_spec('PySide6') is None:
            self.skipTest('Optional PySide6 is not installed')
        import os
        import subprocess
        import sys
        script = r'''
import hashlib, io, json, os, tempfile, time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QUrl
from polaris_platform.desktop.updates import UpdateController
from polaris_platform.updates import API_URL, architecture
app = QGuiApplication([])
app.setApplicationName('PolarisUpdateTest')
payload = b'fake deb for integration test'
name = 'polaris_99.0.0.0_' + architecture() + '.deb'
data = {'tag_name':'v99.0.0.0', 'assets':[{'name':name, 'size':len(payload),
 'browser_download_url':'https://github.com/gonerain/Polaris-desktop/releases/download/v99.0.0.0/' + name,
 'digest':'sha256:' + hashlib.sha256(payload).hexdigest()}]}
def respond(url, **kwargs):
 return io.BytesIO(json.dumps(data).encode() if url == API_URL else payload)
def finish(controller):
 deadline = time.monotonic() + 5
 while controller.busy and time.monotonic() < deadline:
  app.processEvents()
  time.sleep(.01)
 assert not controller.busy, 'Worker did not finish'
with tempfile.TemporaryDirectory() as folder:
 os.environ['XDG_CACHE_HOME'] = folder
 controller = UpdateController(app)
 controller.show()
 app.processEvents()
 assert controller._view.rootObject() is not None, controller._view.errors()
 with patch('polaris_platform.updates._open', side_effect=respond):
  controller.check()
  finish(controller)
  assert controller.canDownload and not controller.canInstall
  controller.download()
  finish(controller)
 assert controller.canInstall and not controller.canDownload
 assert controller._download.read_bytes() == payload
 assert 'sudo apt install' in controller.installCommand
 with patch('polaris_platform.desktop.updates.QDesktopServices.openUrl', return_value=False):
  controller.install()
 assert 'sudo apt install' in controller.message
 controller._view.close()
 controller._view.setSource(QUrl())
'''
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
