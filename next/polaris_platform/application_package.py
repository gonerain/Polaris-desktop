"""Local trusted Qt Quick application packages with verified snapshots."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from uuid import uuid4

from .application import Application
from .protocol import PlatformError


MANIFEST = 'polaris-application.json'


def _invalid(message):
    raise PlatformError('invalid_application_package', message)


def _manifest(root):
    try:
        value = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as error:
        raise PlatformError('invalid_application_package', 'Cannot read application manifest') from error
    if not isinstance(value, dict) or set(value) != {'id', 'name', 'version', 'entry', 'requires'}:
        _invalid('Manifest requires id, name, version, entry and requires')
    for field in ('id', 'name', 'version'):
        if not isinstance(value[field], str) or not value[field].strip():
            _invalid('Manifest identity fields must be nonempty strings')
    entry = value['entry']
    if not isinstance(entry, dict) or set(entry) != {'adapter', 'file'} or entry['adapter'] != 'qt-quick':
        _invalid('Only a qt-quick entry is supported')
    filename = entry['file']
    if not isinstance(filename, str) or not filename or '\\' in filename:
        _invalid('Invalid entry path')
    parts = PurePosixPath(filename)
    if parts.is_absolute() or any(p in ('.', '..') for p in filename.split('/')) or not filename.endswith('.qml'):
        _invalid('Entry must be a relative QML path')
    if not (root / filename).is_file():
        _invalid('Entry QML file does not exist')
    requirements = value['requires']
    if not isinstance(requirements, dict):
        _invalid('Requirements must be an alias map')
    for alias, requirement in requirements.items():
        if (not isinstance(alias, str) or not alias or not isinstance(requirement, dict)
                or set(requirement) != {'componentType', 'operation', 'major', 'access'}
                or any(not isinstance(requirement[k], str) or not requirement[k] for k in ('componentType', 'operation'))
                or type(requirement['major']) is not int or requirement['major'] < 1
                or requirement['access'] not in ('read', 'write')):
            _invalid('Invalid capability requirement')
    return value


def _tree_digest(root):
    """Hash names, file kinds and bytes; reject symlinks and special files."""
    digest = hashlib.sha256()
    def visit(directory, prefix=''):
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            relative = prefix + path.name
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                digest.update(b'D' + relative.encode('utf-8') + b'\0')
                visit(path, relative + '/')
            elif stat.S_ISREG(mode):
                digest.update(b'F' + relative.encode('utf-8') + b'\0')
                size = path.stat().st_size
                digest.update(str(size).encode() + b'\0')
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
            else:
                _invalid('Package must not contain symlinks or special files')
    visit(root)
    return digest.hexdigest()


class ApplicationPackageStore:
    """Install snapshots under a private root; never remove application data."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def install(self, source_directory):
        source = Path(source_directory)
        if source.is_symlink() or not source.is_dir():
            _invalid('Application source must be a directory, not a symlink')
        if self.directory.resolve().is_relative_to(source.resolve()):
            _invalid('Application package store cannot be inside the source directory')
        _tree_digest(source)
        _manifest(source)
        self.directory.mkdir(parents=True, exist_ok=True)
        application_id = uuid4().hex
        temporary = Path(tempfile.mkdtemp(prefix='.install-', dir=self.directory))
        try:
            # symlinks=True preserves any raced symlink so snapshot verification rejects it.
            shutil.copytree(source, temporary / 'snapshot', symlinks=True)
            snapshot = temporary / 'snapshot'
            digest = _tree_digest(snapshot)
            manifest = _manifest(snapshot)
            app = Application(manifest['name'], application_id=application_id,
                              package={'snapshot': application_id, 'digest': digest})
            os.rename(snapshot, self.directory / application_id)
            return app
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def load_verified(self, app):
        if not isinstance(app, Application) or not app.package:
            _invalid('Application has no package')
        root = self.directory / app.id
        if root.is_symlink() or not root.is_dir():
            raise PlatformError('application_package_changed', 'Application snapshot is missing or changed')
        try:
            digest = _tree_digest(root)
            if digest != app.package['digest']:
                raise PlatformError('application_package_changed', 'Application snapshot is missing or changed')
            manifest = _manifest(root)
        except (OSError, PlatformError) as error:
            raise PlatformError('application_package_changed', 'Application snapshot is missing or changed') from error
        return {'entry': str((root / manifest['entry']['file']).absolute()),
                'requires': manifest['requires'], 'manifest': manifest}

    def remove(self, app):
        if not isinstance(app, Application) or not app.package or app.package['snapshot'] != app.id:
            _invalid('Application has no package')
        root = self.directory / app.id
        if root.is_symlink():
            root.unlink()
        elif root.exists():
            shutil.rmtree(root)
