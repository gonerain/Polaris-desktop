"""Local trusted Qt Quick application packages with verified snapshots."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from uuid import uuid4

from .application import ApplicationDefinition
from .protocol import PlatformError


MANIFEST = 'polaris-application.json'


def _invalid(message):
    raise PlatformError('invalid_application_package', message)


def _manifest(root):
    try:
        value = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as error:
        raise PlatformError('invalid_application_package', 'Cannot read application manifest') from error
    if (not isinstance(value, dict) or not {'id', 'name', 'version', 'entry', 'requires'} <= set(value)
            or set(value) - {'id', 'name', 'version', 'entry', 'requires', 'dependencies', 'callbacks'}):
        _invalid('Manifest requires id, name, version, entry and requires')
    dependencies = value.get('dependencies', [])
    if (not isinstance(dependencies, list)
            or any(not isinstance(item, str) or not item.strip() for item in dependencies)
            or len(set(dependencies)) != len(dependencies)):
        _invalid('Dependencies must be unique component type IDs')
    callbacks = value.get('callbacks', {})
    if not isinstance(callbacks, dict):
        _invalid('Callbacks must be an operation map')
    for name, callback in callbacks.items():
        from .contracts import contract_version
        if (not isinstance(name, str) or not name or not isinstance(callback, dict)
                or not {'contract', 'parameters'} <= set(callback)
                or set(callback) - {'contract', 'parameters', 'label'}
                or not isinstance(callback['parameters'], dict)
                or callback['parameters'].get('type') != 'object'
                or ('label' in callback and (not isinstance(callback['label'], str) or not callback['label'].strip()))):
            _invalid('Invalid application callback')
        try:
            contract_version(callback['contract'])
        except PlatformError:
            _invalid('Invalid callback contract')
    for field in ('id', 'name', 'version'):
        if not isinstance(value[field], str) or not value[field].strip():
            _invalid('Manifest identity fields must be nonempty strings')
    entry = value['entry']
    if (not isinstance(entry, dict) or not {'adapter', 'file'} <= set(entry)
            or set(entry) - {'adapter', 'file', 'backend'} or entry['adapter'] != 'qt-quick'):
        _invalid('Only a qt-quick entry is supported')
    if callbacks and 'backend' not in entry:
        _invalid('Callbacks require a backend entry')
    filename = entry['file']
    if not isinstance(filename, str) or not filename or '\\' in filename:
        _invalid('Invalid entry path')
    parts = PurePosixPath(filename)
    if parts.is_absolute() or any(p in ('.', '..') for p in filename.split('/')) or not filename.endswith('.qml'):
        _invalid('Entry must be a relative QML path')
    if not (root / filename).is_file():
        _invalid('Entry QML file does not exist')
    if 'backend' in entry:
        backend = entry['backend']
        if (not isinstance(backend, str) or not backend or chr(92) in backend
                or PurePosixPath(backend).is_absolute()
                or any(part in ('.', '..') for part in backend.split('/'))
                or not backend.endswith('.py') or not (root / backend).is_file()):
            _invalid('Backend must be an existing relative Python path')
    requirements = value['requires']
    if not isinstance(requirements, dict):
        _invalid('Requirements must be an alias map')
    for alias, requirement in requirements.items():
        if not isinstance(alias, str) or not alias or not isinstance(requirement, dict):
            _invalid('Invalid capability requirement')
        if 'contract' in requirement:
            from .contracts import contract_version
            try:
                contract_version(requirement['contract'])
            except PlatformError:
                _invalid('Invalid capability contract')
            if (set(requirement) - {'contract', 'access', 'preferredComponentType', 'label'}
                    or requirement.get('access') not in ('read', 'write')
                    or ('label' in requirement and
                        (not isinstance(requirement['label'], str) or not requirement['label'].strip()))
                    or ('preferredComponentType' in requirement and
                        (not isinstance(requirement['preferredComponentType'], str) or not requirement['preferredComponentType']))):
                _invalid('Invalid capability requirement')
        elif (set(requirement) != {'componentType', 'operation', 'major', 'access'}
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
            app = ApplicationDefinition(manifest['name'], application_id=application_id,
                              package={'snapshot': application_id, 'digest': digest})
            os.rename(snapshot, self.directory / application_id)
            return app
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def load_verified(self, app):
        if not isinstance(app, ApplicationDefinition) or not app.package:
            _invalid('Application has no package')
        root = self.directory / app.package['snapshot']
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
                'backend': (root / manifest['entry']['backend']).absolute() if 'backend' in manifest['entry'] else None,
                'requires': manifest['requires'], 'manifest': manifest}

    def remove(self, app):
        if not isinstance(app, ApplicationDefinition) or not app.package:
            _invalid('Application has no package')
        root = self.directory / app.package['snapshot']
        if root.is_symlink():
            root.unlink()
        elif root.exists():
            shutil.rmtree(root)
