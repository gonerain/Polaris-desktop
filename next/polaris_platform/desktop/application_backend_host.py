"""Trusted host controls for application-owned background services."""
import json
import threading
from PySide6.QtCore import QTimer
from .management_control import ManagementControlPort
from ..application import ApplicationDefinition
from ..application_backend import ApplicationBackend
from ..persistence import read_json, write_json
from ..protocol import PlatformError


class ApplicationBackendHost:
    def _configure_backends(self, directory):
        self._backend_warnings = {}
        self._backend_dependencies = {}
        if not hasattr(self, '_dependency_timer'):
            self._dependency_timer = QTimer(self)
            self._dependency_timer.setInterval(1000)
            self._dependency_timer.timeout.connect(self._check_backend_dependencies)
        self._dependency_timer.start()
        self._backend_intent_path = directory / 'application-background.json' if directory is not None else None
        self._backend_intents = read_json(self._backend_intent_path, {}) if directory is not None else {}
        if not isinstance(self._backend_intents, dict) or any(type(v) is not bool for v in self._backend_intents.values()):
            raise PlatformError('invalid_application_state', 'Invalid application background intentions')

    def _set_backend_intent(self, identity, enabled):
        self._backend_intents[identity] = enabled
        write_json(self._backend_intent_path, self._backend_intents)

    def _clear_backend_intent(self, identity):
        if self._backend_intents.get(identity):
            self._set_backend_intent(identity, False)

    def _backend_available(self, identity):
        app = self.store.load(identity)
        return bool(app.package and self.packages.load_verified(app).get('backend'))

    def _background_enabled(self, identity):
        return bool(self._backend_intents.get(identity))

    def _backend_component_started(self, identity):
        if not self._closed and self._background_enabled(identity):
            try:
                self._activate_backend(self.store.load(identity))
            except Exception as error:
                self._backend_errors[identity] = str(error)
                self.changed.emit()

    def _backend_component_stopped(self, identity):
        runner = self._backends.get(identity)
        if runner is not None:
            runner.stop()
        if not self._closed:
            self._clear_backend_intent(identity)
        self.changed.emit()

    def _verify_component_dependencies(self, app, verified):
        instances = self.runtime.list_instances()
        types = {row['componentType'] for row in instances}
        missing = [kind for kind in verified['manifest'].get('dependencies', []) if kind not in types]
        identities = {row['instanceId'] for row in instances}
        missing.extend(sorted({binding['instanceId'] for binding in app.bindings.values()
                               if binding['instanceId'] not in identities}))
        if missing:
            raise PlatformError('application_dependency_missing', '依赖组件丢失：' + '、'.join(missing))

    def _check_backend_dependencies(self):
        if self._closed:
            self._dependency_timer.stop()
            return
        for identity, (app, verified) in self._backend_dependencies.copy().items():
            runner = self._backends.get(identity)
            if runner is None or not runner.running:
                continue
            try:
                self._verify_component_dependencies(app, verified)
            except PlatformError as error:
                self._backend_errors[identity] = str(error)
                self._stop_application(identity)
                self.changed.emit()

    def _check_backend_capabilities(self, app, verified):
        aliases, warnings = [], []
        for alias in verified['requires']:
            try:
                self._verify_binding(app, alias)
            except PlatformError as error:
                if error.code not in {'application_binding_missing', 'application_binding_unavailable',
                                      'application_binding_unsupported'}:
                    raise
                warnings.append(str(error))
            else:
                aliases.append(alias)
        self._backend_warnings[app.id] = warnings
        return aliases

    def _activate_backend(self, app):
        if app.id in self._package_updates:
            raise PlatformError('application_updating', '应用正在更新')
        previous = self._backends.get(app.id)
        if previous is not None:
            if previous.stopping:
                raise PlatformError('application_stopping', '应用后台正在停止，请等待当前任务结束')
            if previous.running:
                return
        verified = self.packages.load_verified(app)
        backend = verified.get('backend')
        if backend is None:
            raise PlatformError('application_backend_missing', '此应用没有后台入口')
        self._verify_component_dependencies(app, verified)
        aliases = self._check_backend_capabilities(app, verified)
        client = self.runtime.application_client(app.id)
        context = self.runtime.application_context(app.id)
        try:
            client.require_permissions([(app.bindings[a]['target'], app.bindings[a]['operation']) for a in aliases], context)
        except PlatformError as error:
            if error.code not in {'permission_required', 'permission_denied'}:
                raise
            self._backend_warnings[app.id].append(str(error))
        session = app.open(client, context, self.runtime.status)
        runner = ApplicationBackend(app, session, backend, self.application_data_directory(app.id), self.changed.emit)
        self._backends[app.id] = runner
        self._backend_dependencies[app.id] = (app, verified)
        self._backend_errors.pop(app.id, None)
        runner.start()

    def _restore_backends(self):
        for identity, enabled in self._backend_intents.copy().items():
            if not enabled:
                continue
            try:
                app = self.store.load(identity)
                self._verify_component_dependencies(app, self.packages.load_verified(app))
                self._ensure_application(app, restore=True)
                self.runtime.start_application(identity)
                if identity not in self._backends and identity not in self._backend_errors:
                    self._activate_backend(app)
            except Exception as error:
                self._backend_errors[identity] = str(error)
        self.changed.emit()

    def start_backend(self, identity):
        self._local_input()
        if identity in self._package_updates:
            raise PlatformError('application_updating', '应用正在更新')
        app = self.store.load(identity)
        verified = self.packages.load_verified(app)
        if verified.get('backend') is None:
            raise PlatformError('application_backend_missing', '此应用没有后台入口')
        if identity in self._approval_tokens:
            return
        previous = self._backends.get(identity)
        if previous and previous.stopping:
            raise PlatformError('application_stopping', '应用后台正在停止，请等待当前任务结束')
        if previous and previous.running:
            return
        self._verify_component_dependencies(app, verified)
        aliases = self._check_backend_capabilities(app, verified)
        self._ensure_application(app)
        self.runtime.start_application(identity)
        client = self.runtime.application_client(identity)
        context = self.runtime.application_context(identity)
        try:
            client.require_permissions([(app.bindings[a]['target'], app.bindings[a]['operation']) for a in aliases], context)
        except PlatformError as error:
            if error.code != 'permission_required':
                raise
        else:
            self._set_backend_intent(identity, True)
            self._activate_backend(app)
            self.changed.emit()
            return
        execution = ApplicationDefinition.from_dict(app.as_dict())
        execution.flows['__background_start__'] = [{'alias': alias, 'params': {}} for alias in aliases]
        def unchanged():
            try:
                return not self._closed and self.store.load(identity).as_dict() == app.as_dict()
            except PlatformError:
                return False
        def approved(outcome):
            self._approval_tokens.pop(identity, None)
            self._hold('application', False)
            if not unchanged():
                return
            if outcome != 'confirmed':
                self._backend_errors[identity] = '后台启动授权已取消或失败'
                self.changed.emit()
                return
            try:
                self._set_backend_intent(identity, True)
                self._activate_backend(app)
            except Exception as error:
                self._backend_errors[identity] = str(error)
            self.changed.emit()
        self._hold('application', True)
        try:
            token = ManagementControlPort(self.runtime).request_application(
                execution.as_dict(), '__background_start__', approved, unchanged)
        except Exception:
            self._hold('application', False)
            raise
        self._approval_tokens[identity] = token

    def stop_backend(self, identity):
        self._local_input()
        self._clear_backend_intent(identity)
        token = self._approval_tokens.pop(identity, None)
        if token:
            ManagementControlPort(self.runtime).cancel_approval(token)
            self._hold('application', False)
        self._stop_application(identity)
        self._update_views()
        self.changed.emit()

    def _backend_callback(self, identity, command, params):
        runner = self._backends.get(identity)
        if runner is None or not runner.running or runner.stopping:
            raise PlatformError('completion_not_ready', '应用后台尚未运行')
        try:
            return runner.call(command, params)
        except PlatformError as error:
            if error.code != 'application_backend_starting':
                raise
            raise PlatformError('completion_not_ready', '应用后台正在启动') from error

    def backend_call(self, bridge, command, params, request_id):
        self._local_input()
        if not bridge.enabled:
            raise PlatformError('application_inactive', '此应用界面当前未打开')
        runner = self._backends.get(bridge.application_id)
        if runner is None or not runner.running:
            raise PlatformError('application_backend_stopped', '请先启动应用后台')
        def execute():
            try:
                result = json.dumps(runner.call(command, dict(params)), ensure_ascii=False, allow_nan=False)
                bridge.delivered.emit(runner, request_id, result, '')
            except Exception as error:
                bridge.delivered.emit(runner, request_id, '', str(error))
        threading.Thread(target=execute, daemon=True, name='application-command').start()
