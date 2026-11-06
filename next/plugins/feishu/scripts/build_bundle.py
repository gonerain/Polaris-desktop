#!/usr/bin/env python3
"""Assemble a locked Linux x86-64 Feishu component without installing packages."""
import argparse
import email
import hashlib
import json
import platform
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def files(root):
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Dependency tree contains a symlink')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo') and path.relative_to(root).parts[0] != 'bin' and not (path.parent.name.endswith('.dist-info') and path.name in ('RECORD', 'REQUESTED', 'direct_url.json')):
            yield path


def tree_digest(root):
    digest = hashlib.sha256()
    for path in files(root):
        name, data = path.relative_to(root).as_posix().encode(), path.read_bytes()
        for value in (name, data):
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies', type=Path, required=True, help='Pre-resolved dependency directory')
    parser.add_argument('--wheels', type=Path, required=True, help='Directory containing the exact locked wheels')
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    deps, output = args.dependencies.resolve(), args.output.resolve()
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or sys.version_info[:2] != (3, 10):
        parser.error('This lock targets Linux x86_64 and Python 3.10')
    if output.exists() or output.is_relative_to(ROOT) or output.is_relative_to(deps):
        parser.error('Output must be a new directory outside the source and dependencies')
    lock = json.loads((ROOT / 'dependencies.lock.json').read_text(encoding='utf-8'))
    if tree_digest(deps) != lock['vendorTreeSha256']:
        parser.error('Dependency tree digest mismatch')
    actual = {}
    for metadata in deps.glob('*.dist-info/METADATA'):
        dist = email.message_from_bytes(metadata.read_bytes())
        actual[dist['Name']] = dist['Version']
    if actual != lock['distributions']:
        parser.error('Dependency versions mismatch')
    for wheel_name, expected in lock['wheels'].items():
        wheel = args.wheels / wheel_name
        if not wheel.is_file() or hashlib.sha256(wheel.read_bytes()).hexdigest() != expected:
            parser.error('Missing or mismatched wheel: ' + wheel_name)
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.endswith('/') or '.data/' in name or name.endswith('.dist-info/RECORD'):
                    continue
                if not (deps / name).is_file() or archive.read(name) != (deps / name).read_bytes():
                    parser.error('Dependency tree differs from wheel: ' + wheel_name)
    manifest = ROOT / 'manifest.json'
    package = ROOT / 'polaris_feishu_bot'
    if not manifest.is_file() or not package.is_dir():
        parser.error('Component manifest or implementation is incomplete')
    output.mkdir(parents=True)
    try:
        shutil.copy2(manifest, output / 'manifest.json')
        shutil.copytree(package, output / package.name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        shutil.copy2(ROOT / 'dependencies.lock.json', output / 'dependencies.lock.json')
        shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', output / 'THIRD_PARTY_NOTICES.md')
        shutil.copy2(ROOT / 'SETUP.md', output / 'SETUP.md')
        shutil.copy2(ROOT / 'README.md', output / 'README.md')
        for path in files(deps):
            target = output / 'vendor' / path.relative_to(deps)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        if tree_digest(output / 'vendor') != lock['vendorTreeSha256']:
            raise ValueError('Output vendor verification failed')
    except Exception:
        shutil.rmtree(output)
        raise
    print(json.dumps({'output': str(output), 'vendorTreeSha256': lock['vendorTreeSha256'], 'platform': lock['platform']}))


if __name__ == '__main__':
    main()
