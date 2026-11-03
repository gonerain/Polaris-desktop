# -*- mode: python ; coding: utf-8 -*-
"""Build Polaris and its platform components; plugin sources are installed separately."""
from pathlib import Path
import os
import sys
import sysconfig
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root / 'next'))
from polaris_platform.metadata import APP_NAME, VERSION, AUTHOR, PROJECT_URL

# Component entry packages are reloaded by the source loader at lifecycle start.
# Frozen bytecode alone cannot satisfy that loader's filesystem reads.
datas = collect_data_files('polaris_platform', include_py_files=True) + collect_data_files('components', include_py_files=True)
datas += [(str(path), 'next') for path in sorted((root / 'next').glob('config.*.json'))]
for filename in ('LICENSE', 'README.md', 'CHANGELOG.md'):
    if (root / filename).is_file():
        datas.append((str(root / filename), '.'))

# Platform imports include the SDK and Qt adapters. External plugins own their dependencies.
hiddenimports = set(collect_submodules('polaris_platform') + collect_submodules('components'))
# The default Weixin plugin renders its login code locally with the SVG backend.
hiddenimports.update(('qrcode', 'qrcode.image.svg'))
# External Python plugins share the host's standard library. Collect this
# general baseline independently of installed plugin code or third-party deps.
stdlib = Path(sysconfig.get_path('stdlib'))
skipped = {'site-packages', 'dist-packages', 'test', 'tests', '__pycache__',
           'idlelib', 'tkinter', '_tkinter', 'turtledemo'}
hiddenimports.update(name for name in sys.stdlib_module_names
                     if name not in skipped and name not in {'antigravity', 'this', 'turtle'})
stdlib_files = []
for directory, children, files in os.walk(stdlib):
    children[:] = [name for name in children if name not in skipped]
    stdlib_files.extend(Path(directory) / name for name in files if name.endswith('.py'))
for path in stdlib_files:
    parts = path.relative_to(stdlib).with_suffix('').parts
    if any(part in skipped for part in parts) or not all(part.isidentifier() for part in parts):
        continue
    if parts[-1] in {'__main__', 'antigravity', 'this', 'turtle'}:
        continue
    if parts[-1] == '__init__':
        parts = parts[:-1]
    if parts:
        hiddenimports.add('.'.join(parts))

# Generate the Windows resource from the same version constant used by the CLI.
version_resource = None
if sys.platform == 'win32':
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
        VarFileInfo, VarStruct,
    )
    parts = tuple(int(part) for part in VERSION.split('.'))
    version_resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=parts, prodvers=parts, mask=0x3f, flags=0,
                          OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', AUTHOR), StringStruct('FileDescription', APP_NAME),
            StringStruct('FileVersion', VERSION), StringStruct('InternalName', APP_NAME),
            StringStruct('OriginalFilename', APP_NAME + '.exe'),
            StringStruct('ProductName', APP_NAME), StringStruct('ProductVersion', VERSION),
            StringStruct('Comments', PROJECT_URL),
        ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])],
    )

a = Analysis(
    [str(root / 'main.py')], pathex=[str(root / 'next')], binaries=[], datas=datas,
    hiddenimports=sorted(hiddenimports), hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'idlelib', 'turtledemo', 'turtle'], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME, version=version_resource,
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name=APP_NAME)
