#!/usr/bin/env python3
"""Build the frozen application and an upgradeable Debian package on Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'next'))
from polaris_platform.metadata import VERSION, PROJECT_URL


def write(root, name, content, mode=0o644):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    target.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-freeze', action='store_true', help='Package an already built dist/Polaris (version is checked)')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('deb packages must be built on Linux')
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if not arch:
        parser.error('supported build architectures: x86_64, aarch64')
    if not shutil.which('dpkg-deb'):
        parser.error('dpkg-deb is required')
    if not args.skip_freeze:
        env = os.environ.copy()
        env.setdefault('XDG_CACHE_HOME', str(ROOT / 'build' / 'cache'))
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT / 'Polaris.spec')], cwd=ROOT, env=env, check=True)
    frozen = ROOT / 'dist' / 'Polaris'
    actual = subprocess.check_output([str(frozen / 'Polaris'), '--version'], text=True).strip()
    if actual != f'Polaris v{VERSION}':
        parser.error(f'frozen executable is stale: {actual}; expected v{VERSION}')
    # Exercise the real GUI path on a fresh installation and on restart. A CLI
    # version check cannot detect missing source, QML, or bundled skin assets.
    with tempfile.TemporaryDirectory(prefix='polaris-desktop-smoke-') as state:
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
        identities = []
        for phase in ('first launch', 'restart'):
            result = subprocess.run([str(frozen / 'Polaris'), '--component-python',
                                     str(ROOT / 'tools/smoke_frozen_desktop.py'), state],
                                    cwd=state, env=env, capture_output=True, text=True, timeout=20)
            if result.returncode:
                raise RuntimeError(f'Frozen desktop {phase} failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}')
            report = json.loads(result.stdout.strip().splitlines()[-1])
            if not report['petVisible'] or not report['skinReady']:
                raise RuntimeError(f'Frozen desktop {phase} did not show a ready pet')
            identities.append(report['installation'])
            print(f'Desktop {phase}: pet visible, bundled skin ready', flush=True)
        if identities[0] != identities[1]:
            raise RuntimeError('Restart did not preserve the pet installation')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    package = output / f'polaris_{VERSION}_{arch}.deb'
    with tempfile.TemporaryDirectory(prefix='polaris-deb-') as temporary:
        stage = Path(temporary)
        stage.chmod(0o755)
        app = stage / 'opt' / 'polaris'
        shutil.copytree(frozen, app, symlinks=True)
        write(stage, 'usr/bin/polaris', '#!/bin/sh\nexec /opt/polaris/Polaris "$@"\n', 0o755)
        for name in ('polaris.desktop',):
            target = stage / 'usr/share/applications' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / 'packaging/debian' / name, target)
            if shutil.which('desktop-file-validate'):
                subprocess.run(['desktop-file-validate', str(target)], check=True)
        # Convert the bundled application artwork locally, preserving its attribution.
        from PySide6.QtGui import QImage
        icon = QImage(str(ROOT / 'next/components/pet/skins/dshpet/poster.webp'))
        if icon.isNull():
            raise RuntimeError('Application icon could not be loaded')
        icon_path = stage / 'usr/share/icons/hicolor/256x256/apps/polaris.png'
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        from PySide6.QtCore import Qt
        if not icon.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(icon_path)):
            raise RuntimeError('Application icon could not be saved')
        docs = stage / 'usr/share/doc/polaris'
        docs.mkdir(parents=True)
        shutil.copy2(ROOT / 'LICENSE', docs / 'copyright')
        for name in ('ATTRIBUTION.md', 'CC-BY-NC-SA-4.0.txt', 'UPSTREAM-MIT.txt', 'UPSTREAM-NOTICE.md'):
            shutil.copy2(ROOT / 'next/components/pet/skins/dshpet' / name, docs / name)
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024
        write(stage, 'DEBIAN/control', f'''Package: polaris
Version: {VERSION}
Section: utils
Priority: optional
Architecture: {arch}
Maintainer: gonerain <gonerain@users.noreply.github.com>
Installed-Size: {size}
Depends: ca-certificates, libc6 (>= 2.35), libstdc++6 (>= 12), libgcc-s1, zlib1g, libgl1, libegl1, libopengl0, libx11-6, libxcb1, libxkbcommon0, libdbus-1-3, libcrypt1, libnsl2, libdrm2, libwayland-client0, libwayland-cursor0, libwayland-egl1, libwayland-server0
Recommends: xdg-utils
Homepage: {PROJECT_URL}
Description: Polaris desktop component workspace
 Independent desktop components with a canvas and bundled pet artwork.
 Includes a GitHub Release update checker and verified deb downloads.
 Code is MIT; bundled artwork is CC BY-NC-SA 4.0 (non-commercial).
''')
        # No maintainer script modifies home directories or stops running sessions.
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(stage), str(package)], check=True)
    digest = sha256(package)
    package.with_suffix('.deb.sha256').write_text(f'{digest}  {package.name}\n')
    print(package)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


if __name__ == '__main__':
    main()
