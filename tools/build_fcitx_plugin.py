#!/usr/bin/env python3
"""Build the Linux Fcitx input plugin against the same Qt as PySide6.

Requires CMake, Ninja, ECM, X11/XCB/xkbcommon development files, a Qt SDK
(including private headers), and an fcitx5-qt source checkout.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from PySide6.QtCore import QLibraryInfo, QPluginLoader, qVersion

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qt-prefix', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    qt = args.qt_prefix.resolve()
    source = args.source.resolve()
    build = ROOT / 'build' / 'fcitx5-qt'
    env = dict(os.environ)
    # Use PySide's runtime libraries for SDK tools as well as for validation.
    libraries = QLibraryInfo.path(QLibraryInfo.LibrariesPath)
    env['LD_LIBRARY_PATH'] = libraries
    version = subprocess.check_output([str(qt / 'bin/qmake'), '-query', 'QT_VERSION'], env=env, text=True).strip()
    if version != qVersion():
        raise RuntimeError(f'Qt SDK {version} does not match PySide Qt {qVersion()}')
    subprocess.run([
        'cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
        f'-DCMAKE_PREFIX_PATH={qt}', '-DENABLE_QT5=OFF', '-DENABLE_QT6=ON',
        '-DBUILD_ONLY_PLUGIN=ON', '-DENABLE_QT6_WAYLAND_WORKAROUND=OFF',
        '-DCMAKE_BUILD_TYPE=Release',
    ], env=env, check=True)
    subprocess.run(['cmake', '--build', str(build), '-j4'], env=env, check=True)
    plugin = build / 'qt6/platforminputcontext/libfcitx5platforminputcontextplugin.so'
    loader = QPluginLoader(str(plugin))
    if not loader.load():
        raise RuntimeError(loader.errorString())
    loader.unload()
    destination = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / 'platforminputcontexts' / plugin.name
    shutil.copy2(plugin, destination)
    # Ship the matching source and licenses with the frozen plugin (LGPL).
    licenses = ROOT / 'build' / 'fcitx5-qt-licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    for name in ('BSD-3-Clause.txt', 'LGPL-2.1-or-later.txt'):
        shutil.copy2(source / 'LICENSES' / name, licenses / name)
    with tarfile.open(licenses / 'fcitx5-qt-source.tar.gz', 'w:gz') as archive:
        archive.add(source, arcname='fcitx5-qt', filter=lambda entry: None if '.git' in Path(entry.name).parts else entry)
    print(destination)


if __name__ == '__main__':
    main()
