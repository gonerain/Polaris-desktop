"""Validate the publishable marketplace and compare package versions to a Git base."""
import argparse
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'next'))
from components.sources import Sources


def catalog(path):
    Sources._validate_links(path.resolve())
    name, components, applications = object.__new__(Sources)._index(path.resolve())
    return {(item['type'], item['manifest']['id']): item for item in components + applications}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', help='Git base revision used to compare package content and versions')
    args = parser.parse_args()
    current = catalog(ROOT / 'marketplace')
    if args.base:
        subprocess.run(['git', 'rev-parse', '--verify', args.base + '^{commit}'],
                       cwd=ROOT, capture_output=True, check=True)
        exists = subprocess.run(['git', 'cat-file', '-e', args.base + ':marketplace/polaris-source.json'],
                                cwd=ROOT, capture_output=True)
        if exists.returncode == 0:
            with tempfile.TemporaryDirectory(prefix='polaris-market-base-') as temp:
                archive = Path(temp) / 'base.tar'
                with archive.open('wb') as output:
                    subprocess.run(['git', 'archive', args.base, 'marketplace'], cwd=ROOT, stdout=output, check=True)
                with tarfile.open(archive) as source:
                    source.extractall(temp, filter='data')
                previous = catalog(Path(temp) / 'marketplace')
                for key, entry in current.items():
                    old = previous.get(key)
                    if old and old['contentDigest'] != entry['contentDigest'] and old['manifest']['version'] == entry['manifest']['version']:
                        raise SystemExit(f'{key[0]} {key[1]}: package content changed without a version change')
    print(f'Marketplace valid: {len(current)} packages')


if __name__ == '__main__':
    main()
