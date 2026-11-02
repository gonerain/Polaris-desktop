"""Reconcile the manager's default plugin sources with this desktop installation."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot


def configured_sources(config):
    if 'defaultSources' in config:
        return config['defaultSources']
    return json.loads(Path(__file__).with_name('default-sources.json').read_text(encoding='utf-8'))


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
        self.errors = {}
        self.pending = set()
        self.failed_starts = {}
        self.cancelled = threading.Event()
        self.fetched.connect(self._finish)

    def configure(self, specs):
        for spec in specs:
            source_id = self.control.preset(spec)
            self.specs[source_id] = spec
            self.request(source_id)

    def _existing(self, component):
        return next((r for r in self.runtime.export_installations() if r['manifest']['id'] == component), None)

    def _active(self):
        return (not self.cancelled.is_set() and self.runtime.status('sources')['state'] == 'running'
                and self.runtime.component_instance('sources') is self.provider)

    def request(self, source_id):
        spec = self.specs[source_id]
        component = spec['component']
        if not self._active() or source_id in self.pending or component in self.runtime.removed_installations():
            return
        existing = self._existing(component)
        retry_start = existing and self.failed_starts.get(source_id) == existing['installationId']
        if existing and not retry_start and not missing_legacy_directory(existing, spec):
            return
        self.errors.pop(source_id, None)
        self.pending.add(source_id)
        self.changed.emit()

        def fetch():
            error = ''
            try:
                self.control.fetch_preset(source_id, self.cancelled.is_set)
            except Exception as exc:
                error = str(exc)
            if not self.cancelled.is_set():
                self.fetched.emit(source_id, error)
        threading.Thread(target=fetch, name='default-plugin-source', daemon=True).start()

    @Slot(str, str)
    def _finish(self, source_id, error):
        self.pending.discard(source_id)
        try:
            if not self._active():
                return
            if error:
                raise ValueError(error)
            spec = self.specs[source_id]
            component = spec['component']
            if component in self.runtime.removed_installations():
                return
            existing = self._existing(component)
            retry_start = existing and self.failed_starts.get(source_id) == existing['installationId']
            if retry_start:
                if self.runtime.status(component)['state'] != 'failed':
                    return
            elif existing and not missing_legacy_directory(existing, spec):
                return
            else:
                entry = next((row for row in self.control.catalog(source_id) if row['manifest']['id'] == component), None)
                if entry is None:
                    raise ValueError(f'插件源没有声明 {component}')
                installed = self.control.install(source_id, component, replace=bool(existing),
                    expected_installation=existing['installationId'] if existing else None, expected_revision=entry['revision'])
                if existing and not existing['autostart']:
                    return
                self.failed_starts[source_id] = installed['installationId']
            self.runtime.start_component(component)
            self.failed_starts.pop(source_id, None)
        except Exception as exc:
            self.errors[source_id] = str(exc)
        finally:
            self.changed.emit()

    def rows(self, sources):
        return [dict(source, pending=source['id'] in self.pending, defaultError=self.errors.get(source['id'], ''))
                for source in sources]
