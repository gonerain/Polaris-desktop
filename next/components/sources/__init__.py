"""Repository catalogs and immutable plugin installations owned by this component."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import RLock
from uuid import uuid4

from polaris_platform.component import Component
from polaris_platform.persistence import read_json, write_json
from polaris_platform.protocol import PlatformError
from polaris_platform.runtime import Runtime, _active


class Sources(Component):
    def __init__(self, control, state_dir):
        super().__init__()
        self._control = control
        self._root = Path(state_dir).resolve() / 'sources'
        self._root.mkdir(parents=True, exist_ok=True)
        self._storage = self._root / 'records.json'
        self._data = read_json(self._storage, {'sources': {}, 'installations': {}})
        self._lock = RLock()
        self.operation('sources')(lambda p, c: self.sources())
        self.operation('catalog')(lambda p, c: self.catalog(p.get('source_id')))

    def local_source_control(self):
        self._trusted()
        return _SourceControl(self)

    @staticmethod
    def _trusted():
        if _active.get() is not None:
            raise PlatformError('permission_denied', 'Plugin source changes require trusted local management')

    def sources(self):
        with self._lock:
            return deepcopy(list(self._data['sources'].values()))

    def catalog(self, source_id=None):
        with self._lock:
            records = self._data['sources'].values() if source_id is None else [self._source(source_id)]
            return deepcopy([dict(sourceId=s['id'], revision=s['revision'], **item)
                             for s in records for item in s['components']])

    def _source(self, source_id):
        if source_id not in self._data['sources']:
            raise PlatformError('unknown_source', source_id)
        return self._data['sources'][source_id]

    def _save(self):
        write_json(self._storage, self._data)

    @staticmethod
    def _git(*args):
        env = dict({k: v for k, v in os.environ.items() if not k.startswith('GIT_')}, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT='0')
        # Explicitly disable executable hooks and external protocol helpers.
        command = ['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'protocol.ext.allow=never', *map(str, args)]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise PlatformError('source_fetch_failed', result.stderr.strip())
        return result.stdout.strip()

    @staticmethod
    def _inside(root, relative):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise PlatformError('invalid_source', 'Component path must be relative')
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()):
            raise PlatformError('invalid_source', 'Component path escapes repository')
        return target

    def _index(self, root):
        index = read_json(root / 'polaris-source.json', None)
        if not isinstance(index, dict) or type(index.get('schemaVersion')) is not int or index['schemaVersion'] != 1:
            raise PlatformError('invalid_source', 'Expected polaris-source.json schemaVersion 1')
        if not isinstance(index.get('components'), list) or not isinstance(index.get('name'), str):
            raise PlatformError('invalid_source', 'Source requires name and components')
        components, ids = [], set()
        for item in index['components']:
            if not isinstance(item, dict):
                raise PlatformError('invalid_source', 'Component entry must be an object')
            directory = self._inside(root, item.get('path'))
            manifest_path = self._inside(root, str(directory.relative_to(root) / 'manifest.json'))
            manifest = read_json(manifest_path, None)
            Runtime.validate_manifest(manifest)
            if manifest['id'] in ids:
                raise PlatformError('invalid_source', 'Duplicate component ID: ' + manifest['id'])
            ids.add(manifest['id'])
            components.append({'path': item['path'], 'manifest': manifest})
        return index['name'], components

    def _prepare(self, location, ref):
        if ref is not None and (not isinstance(ref, str) or not ref or ref.startswith('-')):
            raise PlatformError('invalid_source', 'Invalid Git revision')
        with tempfile.TemporaryDirectory(dir=self._root, prefix='prepare-') as scratch:
            temporary = Path(scratch)
            root = temporary / 'repository'
            local = Path(location).expanduser()
            is_git = local.is_dir() and (local / '.git').exists()
            remote = location.startswith(('https://', 'ssh://')) or (':' in location and '@' in location.split(':', 1)[0])
            if is_git or remote:
                # Keep Git's read-only objects out of the plugin snapshot on Windows.
                self._git('clone', '--no-checkout', '--no-hardlinks', '--separate-git-dir', temporary / 'git',
                          '--', str(local.resolve()) if is_git else location, root)
                selected = ref or 'HEAD'
                try:
                    revision = self._git('-C', root, 'rev-parse', '--verify', selected + '^{commit}')
                except PlatformError:
                    # clone creates a local branch only for HEAD; other branches
                    # are available through origin's remote tracking refs.
                    revision = self._git('-C', root, 'rev-parse', '--verify', 'refs/remotes/origin/' + selected + '^{commit}')
                self._git('-C', root, 'checkout', '--detach', revision)
                (root / '.git').unlink()
            elif local.is_dir():
                # Resolve before copying: dangling links and links outside the source are rejected.
                local = local.resolve()
                self._validate_links(local)
                shutil.copytree(local, root, symlinks=True, ignore=shutil.ignore_patterns('.git', '__pycache__'))
                revision = self._digest(root)
            else:
                raise PlatformError('invalid_source', 'Expected a local directory or HTTPS/SSH Git repository')
            self._validate_links(root)
            name, components = self._index(root)
            destination = self._root / 'revisions' / uuid4().hex
            destination.parent.mkdir(exist_ok=True)
            shutil.move(str(root), destination)
            return dict(name=name, revision=revision, directory=str(destination), components=components)

    @staticmethod
    def _validate_links(root):
        for path in root.rglob('*'):
            # resolve() also follows Windows directory junctions on supported Python versions.
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                raise PlatformError('invalid_source', 'Link escapes repository: ' + str(path.relative_to(root)))

    @staticmethod
    def _digest(root):
        digest = hashlib.sha256()
        for path in sorted(root.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def _preset(self, spec):
        location = spec['location']
        def canonical(value):
            return value.rstrip('/').removesuffix('.git')
        with self._lock:
            existing = next((s for s in self._data['sources'].values()
                             if canonical(s['location']) == canonical(location) and s['ref'] == spec.get('ref')), None)
            if existing:
                return existing['id']
            source_id = uuid4().hex
            self._data['sources'][source_id] = dict(id=source_id, name=spec['name'], location=location,
                ref=spec.get('ref'), revision=None, directory=None, components=[])
            try:
                self._save()
            except Exception:
                del self._data['sources'][source_id]
                raise
            return source_id

    def _fetch_preset(self, source_id, cancelled):
        # Fetch outside the catalog lock so the manager remains usable while offline.
        with self._lock:
            source = dict(self._source(source_id))
        if source['revision'] or cancelled():
            return
        prepared = self._prepare(source['location'], source['ref'])
        with self._lock:
            current = self._source(source_id)
            if current['revision'] or cancelled():
                shutil.rmtree(prepared['directory'])
                return
            self._data['sources'][source_id] = dict(current, **prepared)
            try:
                self._save()
            except Exception:
                self._data['sources'][source_id] = current
                raise

    def _add(self, location, ref=None):
        location = str(location)
        if Path(location).expanduser().is_dir():
            location = str(Path(location).expanduser().resolve())
        prepared = self._prepare(location, ref)
        source_id = uuid4().hex
        record = dict(id=source_id, location=str(location), ref=ref, **prepared)
        self._data['sources'][source_id] = record
        self._save()
        return deepcopy(record)

    def _refresh(self, source_id, ref=None):
        old = self._source(source_id)
        chosen = ref if ref is not None else old['ref']
        prepared = self._prepare(old['location'], chosen)
        if prepared['revision'] == old['revision']:
            shutil.rmtree(prepared['directory'])
            old['ref'] = chosen
        else:
            old.update(prepared, ref=chosen)
        self._save()
        return deepcopy(old)

    def _install(self, source_id, component_id, replace=False, expected_installation=None, expected_revision=None):
        source = self._source(source_id)
        if expected_revision is not None and source['revision'] != expected_revision:
            raise PlatformError('source_changed', 'Source revision changed; review the selection again')
        matches = [c for c in source['components'] if c['manifest']['id'] == component_id]
        if not matches:
            raise PlatformError('unknown_component', component_id)
        existing = next((i for i in self._control.export_installations() if i['manifest']['id'] == component_id), None)
        if existing and not replace:
            raise PlatformError('already_installed', component_id)
        if expected_installation is not None and (existing is None or existing['installationId'] != expected_installation):
            raise PlatformError('installation_changed', component_id)
        item = matches[0]
        path = str(self._inside(Path(source['directory']), item['path']))
        previous = []
        owned = self._data['installations'].get(component_id)
        if existing and owned and owned['sourceId'] == source_id:
            self._assert_owned(component_id, owned)
            if owned['path'] == path:
                return deepcopy(owned)
            previous = deepcopy(owned['previous'])
            if owned['path'] != path:
                previous.append(dict(path=owned['path'], revision=owned['revision']))
        if existing:
            self._switch(component_id, path)
        else:
            try:
                self._control.install_directory(path)
            except ModuleNotFoundError as error:
                raise PlatformError('dependency_unavailable', f'Missing plugin dependency: {error.name}') from error
        identity = next(i['installationId'] for i in self._control.export_installations() if i['manifest']['id'] == component_id)
        self._data['installations'][component_id] = dict(sourceId=source_id, revision=source['revision'], path=path, installationId=identity, previous=previous)
        self._save()
        return deepcopy(self._data['installations'][component_id])

    def _switch(self, component_id, target):
        installed = next((i for i in self._control.export_installations() if i['manifest']['id'] == component_id), None)
        if installed is None:
            raise PlatformError('not_installed', component_id)
        running = any(s['id'] == component_id and s['state'] == 'running' for s in self._control.snapshot())
        try:
            self._control.install_directory(target, replace=True)
        except Exception as error:
            try:
                self._control.install_directory(installed['directory'], replace=True)
                if running:
                    self._control.start_component(component_id)
            except Exception as recovery:
                raise PlatformError('rollback_failed', f'Update failed: {error}; restoring previous code failed: {recovery}') from error
            if isinstance(error, ModuleNotFoundError):
                raise PlatformError('dependency_unavailable', f'Missing plugin dependency: {error.name}') from error
            raise

    def _restore_installations(self, before, component_id):
        previous = {row['manifest']['id']: row for row in before}
        for current in self._control.export_installations():
            identity = current['manifest']['id']
            if identity != component_id:
                continue
            old = previous.get(identity)
            if old is None:
                self._control.uninstall_component(identity)
            elif current['directory'] != old['directory']:
                self._switch(identity, old['directory'])

    def _assert_owned(self, component_id, record):
        installed = next((i for i in self._control.export_installations() if i['manifest']['id'] == component_id), None)
        if installed is None or installed['installationId'] != record.get('installationId') or installed['directory'] != record['path']:
            raise PlatformError('installation_changed', 'Installation changed outside its recorded source; select it again')

    def _update(self, component_id):
        record = self._data['installations'].get(component_id)
        if record is None:
            raise PlatformError('unknown_installation', component_id)
        self._assert_owned(component_id, record)
        source = self._source(record['sourceId'])
        item = next((c for c in source['components'] if c['manifest']['id'] == component_id), None)
        if item is None:
            raise PlatformError('unknown_component', component_id)
        path = str(self._inside(Path(source['directory']), item['path']))
        if record['path'] == path:
            return deepcopy(record)
        self._switch(component_id, path)
        record['previous'].append(dict(path=record['path'], revision=record['revision']))
        record.update(path=path, revision=source['revision'])
        self._save()
        return deepcopy(record)

    def _rollback(self, component_id):
        record = self._data['installations'].get(component_id)
        if not record or not record['previous']:
            raise PlatformError('no_previous_version', component_id)
        self._assert_owned(component_id, record)
        previous = record['previous'][-1]
        self._switch(component_id, previous['path'])
        record.update(record['previous'].pop())
        self._save()
        return deepcopy(record)


class _SourceControl:
    def __init__(self, owner):
        self._owner = owner

    def preset(self, spec):
        self._owner._trusted()
        return self._owner._preset(spec)

    def fetch_preset(self, source_id, cancelled):
        self._owner._trusted()
        self._owner._fetch_preset(source_id, cancelled)

    def __getattr__(self, name):
        if name in {'sources', 'catalog'}:
            return getattr(self._owner, name)
        if name not in {'add', 'refresh', 'install', 'update', 'rollback'}:
            raise AttributeError(name)
        def invoke(*args, **kwargs):
            self._owner._trusted()
            with self._owner._lock:
                position = 1 if name == 'install' else 0
                target = kwargs.get('component_id', args[position] if len(args) > position else None)
                before = deepcopy(self._owner._data)
                installations = self._owner._control.export_installations() if name in {'install', 'update', 'rollback'} else None
                try:
                    return getattr(self._owner, '_' + name)(*args, **kwargs)
                except Exception as error:
                    self._owner._data = before
                    if installations is not None:
                        try:
                            self._owner._restore_installations(installations, target)
                        except Exception as recovery:
                            raise PlatformError('rollback_failed', f'Operation failed: {error}; restoring previous code failed: {recovery}') from error
                    raise
        return invoke


class _InstallationControl:
    """Only the lifecycle operations needed for source installation transactions."""
    def __init__(self, runtime):
        self.__runtime = runtime

    def export_installations(self):
        return self.__runtime.export_installations()

    def snapshot(self):
        return self.__runtime.snapshot()

    def install_directory(self, path, replace=False):
        Sources._trusted()
        return self.__runtime.install_directory(path, replace=replace)

    def uninstall_component(self, component_id):
        Sources._trusted()
        return self.__runtime.uninstall_component(component_id)

    def start_component(self, component_id):
        Sources._trusted()
        return self.__runtime.start_component(component_id)


def create_sources(runtime, state_dir=None):
    directory = state_dir if state_dir is not None else runtime.component_data_directory('sources')
    temporary = tempfile.TemporaryDirectory(prefix='polaris-sources-') if directory is None else None
    component = Sources(_InstallationControl(runtime), temporary.name if temporary else directory)
    component._temporary_storage = temporary
    return component
