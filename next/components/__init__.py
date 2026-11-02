"""Manifests for official components shipped with the platform."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FOUNDATION = ('authorization', 'collaboration', 'runtime')
DESKTOP = ('window', 'canvas', 'pet', 'sources', 'manager')


def manifest(name):
    if name not in FOUNDATION + DESKTOP:
        raise ValueError(f'Unknown bundled component: {name}')
    return json.loads((ROOT / name / 'manifest.json').read_text(encoding='utf-8'))
