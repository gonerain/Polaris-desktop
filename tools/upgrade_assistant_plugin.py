#!/usr/bin/env python3
"""Upgrade a known official polaris_assistant export from the canonical component.

This touches four code files in a local source artifact, never an installed
revision or user data. Refresh that source and update assistant through the
existing source manager afterwards. Unknown/customized exports are rejected.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / 'next/components/assistant'
FILES = ('Chat.qml', '__init__.py', 'view.py', 'settings.py')
# Official export shared by commits 14adab4 through 54672b9.
LEGACY = {
    "Chat.qml": "b67def0638583489114d82eb27f61b24c614398c85a9cf81e1cb143b8d8e799c",
    "__init__.py": "f84e467243e4cfc451fca6c6953d730d9b6dad1e9baa170036f519015a12da6d",
    "view.py": "ee68cc6a4b9e6de5e85939e6997173a79db6faa3c6af9ce1b3fccfbe9d442197",
    "context.py": "44011c4f1faaa1c8bbb7f1e57289bfa8916e6e551d415455c6231ab4e3bdca4e",
    "instructions.py": "86d62ead4a846f8e99fe50d2b1bc4adfa8f97052b0c8fd684f51878d8b598cde",
    "loop.py": "5ac889f15e9b0db49d128d635075315a886b9e206b250563005bc7ff85182067",
    "model.py": "1f5f99f9cb5d49f7b3488d36431d98a1ee765ff288a5013afd920376660b9ce9",
    "tools.py": "54b1edde62fe020f4ddc10cf0cc4b6b6a2d0cdd77f5c6e018ae99be5847128e3",
    "usage.py": "c3b31d92356cdc967235210484aa9c529d13b2e10a504cccd546d10b3e59dac7"
}


def sha(contents):
    return hashlib.sha256(contents).hexdigest()


def data_location(source):
    constructor = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef) and n.name == 'Assistant')
    constructor = next(n for n in constructor.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    return [ast.dump(n.value) for n in constructor.body if isinstance(n, ast.Assign)
            and any((isinstance(t, ast.Name) and t.id == 'base') or
                    (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self' and t.attr == 'data_dir') for t in n.targets)]


def upgrade(destination, backup):
    destination, backup = Path(destination).resolve(), Path(backup).resolve()
    manifest = json.loads((destination / 'manifest.json').read_text())
    if manifest.get('id') != 'assistant' or manifest.get('entry', {}).get('factory') != 'polaris_assistant:create':
        raise ValueError('Only the official legacy polaris_assistant export is supported')
    package = destination / 'polaris_assistant'
    if backup.exists() or backup.is_relative_to(destination) or destination.is_relative_to(backup):
        raise ValueError('Use a new backup directory outside the export')
    for name, legacy in LEGACY.items():
        current = (package / name).read_bytes()
        canonical = (CANONICAL / name).read_bytes()
        allowed = {legacy, sha(canonical)} if name in FILES else {sha(canonical)}
        if sha(current) not in allowed:
            raise ValueError('Unrecognized or customized assistant file: ' + name)
    settings = package / 'settings.py'
    if settings.exists() and settings.read_bytes() != (CANONICAL / settings.name).read_bytes():
        raise ValueError('Customized settings.py requires manual review')
    if data_location((package / '__init__.py').read_text()) != data_location((CANONICAL / '__init__.py').read_text()):
        raise ValueError('Assistant data directory contract differs; migration requires review')
    shutil.copytree(destination, backup, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    before = {name: sha((package / name).read_bytes()) if (package / name).exists() else None for name in FILES}
    staged = []
    try:
        for name in FILES:
            fd, path = tempfile.mkstemp(prefix=name + '.', dir=package)
            staged.append((Path(path), package / name))
            with os.fdopen(fd, 'wb') as stream:
                stream.write((CANONICAL / name).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o644)
        for temporary, target in staged:
            os.replace(temporary, target)
    except Exception:
        for name in FILES:
            original = backup / 'polaris_assistant' / name
            if original.exists():
                shutil.copy2(original, package / name)
            else:
                (package / name).unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return dict(destination=str(destination), backup=str(backup), files=FILES,
                before=before, after={name: sha((package / name).read_bytes()) for name in FILES})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='Local source artifact plugins/assistant directory')
    parser.add_argument('--backup', type=Path, required=True, help='New backup directory outside the artifact')
    args = parser.parse_args()
    try:
        result = upgrade(args.destination, args.backup)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
