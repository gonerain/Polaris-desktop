"""Reconcile the manager's default plugin sources with this desktop installation."""
import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot


def configured_sources(config):
    if 'defaultSources' in config:
        return config['defaultSources']
    specs = json.loads(Path(__file__).with_name('default-sources.json').read_text(encoding='utf-8'))
    resource_root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[3]
    return [dict(spec, location=str(resource_root / spec['bundledDirectory'])) if 'bundledDirectory' in spec else spec
            for spec in specs]


def missing_legacy_directory(record, spec):
    if not record or not record['directory'] or 'legacyDirectory' not in spec:
        return False
    path = Path(record['directory'])
    return (path.parts[-3:] == ('next', 'components', spec['legacyDirectory'])
            and record['manifest']['entry'].get('factory') == spec['legacyFactory']
            and not (path / 'manifest.json').is_file())


class DefaultInstallations(QObject):
    fetched = Signal(str, str)
    changed = Signal()

    def __init__(self, runtime, source_component):
        super().__init__()
        self.runtime = runtime
        self.provider = source_component
        self.control = source_component.local_source_control()
        self.specs = {}
        self.default_catalogs = set()
        self.bundled = set()
        self.migrate_legacy = {}
        self.errors = {}
        self.pending = set()
        self.failed_starts = {}
        self.cancelled = threading.Event()
        self.fetched.connect(self._finish)

    def configure(self, specs):
        source_ids = []
        for spec in specs:
            source_id = self.control.preset(spec)
            targets = spec.get('components', [spec] if 'component' in spec else [])
            if spec.get('defaultCatalog') or 'bundledDirectory' in spec:
                self.default_catalogs.add(source_id)
            if 'bundledDirectory' in spec:
                self.bundled.add(source_id)
            if spec.get('migrateLegacy'):
                self.migrate_legacy[source_id] = spec['migrateLegacy']
            group = self.specs.setdefault(source_id, [])
            for target in targets:
                if not any(existing['component'] == target['component'] for existing in group):
                    group.append(target)
            if source_id not in source_ids:
                source_ids.append(source_id)
        for source_id in source_ids:
            self.request(source_id, load_catalog=source_id in self.default_catalogs)

    def _existing(self, component):
        return next((r for r in self.runtime.export_installations() if r['manifest']['id'] == component), None)

    def _active(self):
        return (not self.cancelled.is_set() and self.runtime.status('sources')['state'] == 'running'
                and self.runtime.component_instance('sources') is self.provider)

    def _needed(self, spec):
        component = spec['component']
        if component in self.runtime.removed_installations():
            return False
        existing = self._existing(component)
        return (not existing or self.failed_starts.get(component) == existing['installationId']
                or missing_legacy_directory(existing, spec))

    def request(self, source_id, load_catalog=False):
        if (not self._active() or source_id in self.pending or
                (not load_catalog and not any(self._needed(spec) for spec in self.specs[source_id]))):
            return
        self.errors.pop(source_id, None)
        self.pending.add(source_id)
        self.changed.emit()

        def fetch():
            error = ''
            try:
                self.control.fetch_preset(source_id, self.cancelled.is_set, refresh=source_id in self.bundled)
            except Exception as exc:
                error = str(exc)
            if not self.cancelled.is_set():
                self.fetched.emit(source_id, error)
        threading.Thread(target=fetch, name='default-plugin-source', daemon=True).start()

    def _install_target(self, source_id, spec):
        component = spec['component']
        if not self._needed(spec):
            return
        existing = self._existing(component)
        retry_start = existing and self.failed_starts.get(component) == existing['installationId']
        if retry_start:
            if self.runtime.status(component)['state'] != 'failed':
                return
        else:
            entry = next((row for row in self.control.catalog(source_id) if row['manifest']['id'] == component), None)
            if entry is None:
                raise ValueError(f'插件源没有声明 {component}')
            installed = self.control.install(source_id, component, replace=bool(existing),
                expected_installation=existing['installationId'] if existing else None, expected_revision=entry['revision'])
            if existing and not existing['autostart']:
                return
            self.failed_starts[component] = installed['installationId']
        self.runtime.start_component(component)
        self.failed_starts.pop(component, None)

    @Slot(str, str)
    def _finish(self, source_id, error):
        self.pending.discard(source_id)
        try:
            if not self._active():
                return
            if error:
                raise ValueError(error)
            if source_id in self.migrate_legacy:
                policy = self.migrate_legacy[source_id]
                retired = {location.rstrip('/').removesuffix('.git') for location in policy['remoteLocations']}
                legacy_ids = [source['id'] for source in self.control.sources()
                              if source['id'] != source_id and
                              (Path(source['location']).is_absolute() or
                               source['location'].rstrip('/').removesuffix('.git') in retired)]
                self.control.archive_sources(legacy_ids, policy['migration'])
            errors = []
            for spec in self.specs[source_id]:
                try:
                    self._install_target(source_id, spec)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise ValueError('; '.join(errors))
        except Exception as exc:
            self.errors[source_id] = str(exc)
        finally:
            self.changed.emit()

    def rows(self, sources):
        return [dict(source, defaultCatalog=source['id'] in self.default_catalogs, pending=source['id'] in self.pending, defaultError=self.errors.get(source['id'], ''))
                for source in sources]
