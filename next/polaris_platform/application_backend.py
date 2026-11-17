"""Packaged application service lifecycle and an alias-only capability context."""
from copy import deepcopy
import importlib.util
import importlib.abc
import importlib.machinery
import json
import sys
import threading
from uuid import uuid4
from .protocol import PlatformError


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def set_data(self, path, data, **kwargs):
        # A verified application snapshot is immutable, including helper modules.
        pass


class _ApplicationImports(importlib.abc.MetaPathFinder):
    def __init__(self, namespace):
        self.namespace = namespace

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.namespace + '.'):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = _SourceOnlyLoader(fullname, spec.origin)
        return spec


class ApplicationBackendContext:
    def __init__(self, application, session, data_directory, publish):
        self.application_id = application.id
        self.data_directory = data_directory
        self.stopped = threading.Event()
        self._bindings = deepcopy(application.bindings)
        self._session = session
        self._publish = publish

    @property
    def bindings(self):
        return deepcopy(self._bindings)

    def call(self, alias, params=None):
        if self.stopped.is_set():
            raise PlatformError('application_closed', self.application_id)
        return self._session.call(alias, params)

    def publish(self, state):
        if not isinstance(state, dict):
            raise PlatformError('invalid_application_state', 'Backend state must be a JSON object')
        value = json.loads(json.dumps(state, allow_nan=False))
        if not self.stopped.is_set():
            self._publish(value)


class ApplicationBackend:
    def __init__(self, application, session, path, data_directory, changed):
        data_directory.mkdir(parents=True, exist_ok=True)
        self.context = ApplicationBackendContext(application, session, data_directory, self._publish)
        self._session, self._path, self._changed = session, path, changed
        self._service = None
        self._state = {}
        self.error = ''
        self.stop_error = ''
        self.running = False
        self.stopping = False
        self._stop_started = False
        self._start_done = threading.Event()
        self.stopped = threading.Event()
        self._module_name = '_polaris_app_' + application.id + '_' + uuid4().hex
        self._imports = _ApplicationImports(self._module_name)

    @property
    def state(self):
        return deepcopy(self._state)

    def _publish(self, state):
        self._state = state
        self._changed()

    def start(self):
        self.running = True
        self._changed()
        threading.Thread(target=self._start, daemon=True, name='application-backend').start()

    def _start(self):
        try:
            sys.meta_path.insert(0, self._imports)
            spec = importlib.util.spec_from_file_location(self._module_name, self._path,
                submodule_search_locations=[str(self._path.parent)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[self._module_name] = module
            # Execute the verified source without generating bytecode inside
            # the immutable package snapshot.
            exec(compile(self._path.read_bytes(), str(self._path), 'exec'), module.__dict__)
            service = module.create(self.context)
            self._service = service
            if self.context.stopped.is_set():
                return
            service.start()
        except Exception as error:
            self.error = str(error)
            self.running = False
            self.context.stopped.set()
            self._session.stop()
            self._changed()
            self.stop()
        finally:
            self._start_done.set()

    def call(self, command, params):
        if self.context.stopped.is_set():
            raise PlatformError('application_closed', self.context.application_id)
        if self._service is None:
            raise PlatformError('application_backend_starting', '应用后台正在启动')
        return self._service.handle(command, params)

    def stop(self):
        if self._stop_started:
            return
        self._stop_started = True
        self.stopping = True
        self.context.stopped.set()
        self._session.stop()
        self.running = False
        self._changed()
        # Application stop must invalidate authority immediately, without waiting
        # for an in-flight model call or application-owned worker to finish.
        threading.Thread(target=self._stop, daemon=True, name='application-backend-stop').start()

    def _stop(self):
        try:
            self._start_done.wait()
            if self._service is not None:
                self._service.stop()
        except Exception as error:
            self.stop_error = str(error)
            self.error = str(error)
            self._changed()
        finally:
            if self._imports in sys.meta_path:
                sys.meta_path.remove(self._imports)
            for name in tuple(sys.modules):
                if name == self._module_name or name.startswith(self._module_name + '.'):
                    sys.modules.pop(name, None)
            self.stopping = False
            self.stopped.set()
            self._changed()
