# -*- mode: python ; coding: utf-8 -*-
"""Build the independent Polaris application; bundled plugins stay loadable sources."""
import ast
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root / 'next'))
from polaris_platform.metadata import APP_NAME, VERSION, AUTHOR, PROJECT_URL

# Keep plugin manifests, code and QML together. They are loaded through the public
# directory loader, rather than frozen as competing copies of their entry packages.
def source_tree(source, target):
    return [(str(path), str(Path(target) / path.relative_to(source).parent))
            for path in sorted(source.rglob('*')) if path.is_file()
            and not any(part in ('__pycache__', 'tests', 'node_modules') for part in path.relative_to(source).parts)
            and path.suffix not in ('.pyc', '.pyo')]

datas = collect_data_files('polaris_platform')
datas += source_tree(root / 'next' / 'components', 'next/components')
datas += source_tree(root / 'next' / 'integrations', 'next/integrations')
datas += [(str(path), 'next') for path in sorted((root / 'next').glob('config.*.json'))]
for filename in ('LICENSE', 'README.md', 'CHANGELOG.md'):
    if (root / filename).is_file():
        datas.append((str(root / filename), '.'))

# Directory-loaded components are intentionally not frozen packages, but their
# runtime imports still need to be collected by Analysis (Qt modules, qrcode and
# standard-library backends used from within those sources).
hiddenimports = set(collect_submodules('polaris_platform'))
# ctypes imports this backend through `from ctypes import wintypes` in the
# directory-loaded credential store, so importing ctypes alone is insufficient.
hiddenimports.add('ctypes.wintypes')
for path in (root / 'next' / 'components').rglob('*.py'):
    if 'tests' in path.parts or '__pycache__' in path.parts:
        continue
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
            [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
        hiddenimports.update(name for name in names if not name.startswith(('polaris_', 'polaris.')))

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
    excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME, version=version_resource,
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name=APP_NAME)
