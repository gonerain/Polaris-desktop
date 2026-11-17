"""Trusted desktop host for application definitions and explicit local input."""
import json
import threading
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QThread

from ..application import Application, ApplicationDefinition, ApplicationStore
from ..protocol import PlatformError, capability
from .management_control import ManagementControlPort
from .application_backend_host import ApplicationBackendHost


class ApplicationHost(ApplicationBackendHost, QObject):
    changed = Signal()
    finished = Signal(int, str, str)
    applicationStopped = Signal(str, str)
    updatePrepared = Signal(str)

    def __init__(self, runtime, hold=None):
        super().__init__()
        self.runtime = runtime
        self.store = None
        self.packages = None
        self._views = {}
        self._backends = {}
        self._backend_errors = {}
        self._backend_intents = {}
        self._package_updates = {}
        self._component_epochs = {}
        self._active_epochs = {}
        self._view_parent = None
        self._presentation_active = False
        self._deliveries = {}
        self._hold = hold or (lambda reason, active: None)
        self._selected, self._state, self._result, self._error = '', 'idle', '', ''
        self._generation = 0
        self._sessions = set()
        self._approval_tokens = {}
        self._notice = ''
        self._feedback = ''
        self._run_app = ''
        self._run_title = ''
        self._closed = False
        self.finished.connect(self._finish)
        self.applicationStopped.connect(self._runtime_stopped)
        self.updatePrepared.connect(self._commit_package_update)

    def configure(self, directory):
        self.store = ApplicationStore(Path(directory) / 'applications') if directory is not None else None
        self._closed = False
        self._configure_backends(Path(directory) if directory is not None else None)
        from ..application_package import ApplicationPackageStore
        self.packages = ApplicationPackageStore(Path(directory) / 'application-packages') if directory is not None else None
        if self.store:
            for definition in self._definitions():
                app = ApplicationDefinition.from_dict(definition)
                try:
                    self._ensure_application(app, restore=True)
                    self.runtime.register_application_bindings(app.id, [binding['instanceId'] for binding in app.bindings.values()])
                except PlatformError as error:
                    # Definitions and existing references remain intact; the
                    # unavailable binding is reported when this app executes.
                    self._notice = app.title + ': ' + error.message
        if self.store:
            store = self.store
            QTimer.singleShot(0, lambda: self._restore_backends()
                              if not self._closed and self.store is store else None)
        self.changed.emit()

    def _definitions(self):
        definitions = []
        if self.store and self.store.directory.exists():
            for path in sorted(self.store.directory.glob('*.json')):
                try:
                    definitions.append(self.store.load(path.stem).as_dict())
                except Exception as error:
                    self._notice = path.name + ': ' + str(error)
        return definitions

    def _local_input(self):
        if QThread.currentThread() != QGuiApplication.instance().thread() or self._closed:
            raise PlatformError('input_thread', '应用操作须来自本机界面')

    @Property(str, notify=changed)
    def applicationsJson(self):
        try:
            return json.dumps(self._definitions(), ensure_ascii=False)
        except Exception as error:
            self._error = str(error)
            return '[]'

    @Property(str, notify=changed)
    def selectedJson(self):
        if not self._selected or not self.store:
            return '{}'
        try:
            return json.dumps(self.store.load(self._selected).as_dict(), ensure_ascii=False)
        except Exception:
            return '{}'

    @Property(str, notify=changed)
    def state(self): return self._state if self._selected == self._run_app else 'idle'

    @Property(bool, notify=changed)
    def busy(self): return self._state in ('running', 'approval')

    @Property(str, notify=changed)
    def busyTitle(self): return self._run_title if self.busy else ''

    @Property(str, notify=changed)
    def result(self): return self._result if self._selected == self._run_app else ''

    @Property(str, notify=changed)
    def feedback(self): return self._feedback

    @Property(str, notify=changed)
    def error(self): return self._notice or (self._error if self._selected == self._run_app else '')

    @Slot(str)
    def select(self, application_id):
        try:
            self._local_input()
            if application_id:
                self.store.load(application_id)
            if (self._selected != application_id and self._selected
                    and not self._background_enabled(self._selected)):
                self._stop_application(self._selected)
            self._selected = application_id
            self._notice = ''
            self._update_views()
        except Exception as error:
            self._notice = str(error)
        self.changed.emit()

    @Slot(str)
    def importJson(self, source):
        try:
            self._local_input()
            if self.store is None:
                raise PlatformError('application_storage_unavailable', '应用存储目录尚未就绪')
            if self._state in ('running', 'approval'):
                raise PlatformError('application_busy', '请等待当前应用操作完成')
            app = ApplicationDefinition.from_dict(json.loads(source))
            # Validate entirely before writing or registering any principal.
            if any(item['applicationId'] == app.id for item in self.store.list()):
                raise PlatformError('application_exists', '此应用身份已存在，请使用新的 applicationId')
            if app.package and any(item.get('package', {}).get('snapshot') == app.package['snapshot']
                                   for item in self.store.list()):
                raise PlatformError('application_snapshot_in_use', '应用快照已由其他应用使用')
            try:
                self.runtime.application_client(app.id)
            except PlatformError as error:
                if error.code != 'unknown_application':
                    raise
            else:
                raise PlatformError('application_identity_reserved', '此应用身份已登记，不能通过导入接管')
            registered = False
            try:
                self._ensure_application(app)
                registered = True
                self.runtime.start_application(app.id)
                client = self.runtime.application_client(app.id)
                for alias, binding in app.bindings.items():
                    status = self.runtime.status(binding['target'])
                    metadata = status.get('description', {}).get('operations', {}).get(binding['operation'], {})
                    if metadata.get('applicationBinding') != 'instance':
                        raise PlatformError('application_binding_unsupported', '能力尚未声明稳定实例应用绑定：' + binding['operation'])
                    handle = client.bind(binding['target'], binding['operation'])
                    if (status['installationId'] != binding['installationId']
                            or status['instanceId'] != binding['instanceId']
                            or list(handle.semantic) != list(binding['semantic'])):
                        raise PlatformError('application_binding_unavailable', alias)
                self.runtime.register_application_bindings(app.id, [binding['instanceId'] for binding in app.bindings.values()])
                self.store.save(app)
            except Exception:
                if registered:
                    self.runtime.unregister_application_principal(app.id)
                raise
            self._selected, self._notice = app.id, ''
        except Exception as error:
            self._notice = str(error)
        self.changed.emit()

    @Slot(str, str)
    def run(self, flow, params_json):
        try:
            self._local_input()
            app = self.store.load(self._selected)
            params = json.loads(params_json)
            self._begin(app, flow, params)
        except Exception as error:
            self._notice = str(error)
            self.changed.emit()

    def _begin(self, app, flow, params, alias=None, delivery=None):
        if self.busy:
            message = '正在执行：' + self._run_title
            self._notice = message
            if delivery is not None:
                bridge, view_generation, request_id = delivery
                bridge.deliver(view_generation, request_id, '', message)
            self.changed.emit()
            return
        try:
            if not isinstance(params, dict):
                raise PlatformError('invalid_application_input', '输入应为对象')
            execution = ApplicationDefinition.from_dict(app.as_dict())
            if alias is not None:
                execution.flows = {'__application_call__': [{'alias': alias, 'input': 'previous'}]}
                flow = '__application_call__'
            if flow not in execution.flows:
                raise PlatformError('application_flow_missing', flow)
            self._ensure_application(app)
            self.runtime.start_application(app.id)
            self._active_epochs[app.id] = self._component_epochs.get(app.id)
            self._generation += 1
            generation = self._generation
            if delivery is not None:
                self._deliveries[generation] = delivery
            self._notice = ''
            self._run_app, self._run_title = app.id, app.title
            self._state, self._result, self._error = 'approval', '', ''
            self._hold('application', True)
            def approved(outcome):
                if self._closed or generation != self._generation:
                    return
                self._approval_tokens.pop(app.id, None)
                try:
                    unchanged = self.store.load(app.id).as_dict() == app.as_dict()
                except Exception:
                    unchanged = False
                if not unchanged:
                    self.finished.emit(generation, '', '应用定义已变化或不可读取，请重新执行')
                    return
                if outcome != 'confirmed':
                    self.finished.emit(generation, '', '授权已取消' if outcome == 'cancelled' else '应用授权失败')
                    return
                try:
                    if app.package:
                        self.packages.load_verified(app)
                    session = execution.open(self.runtime.application_client(app.id),
                                       self.runtime.application_context(app.id), self.runtime.status)
                except Exception as error:
                    self.finished.emit(generation, '', str(error))
                    return
                self._sessions.add(session)
                self._state = 'running'
                self.changed.emit()
                def execute():
                    try:
                        result = session.call(alias, params) if alias is not None else session.run(flow, params)
                        self.finished.emit(generation, json.dumps(result, ensure_ascii=False, indent=2), '')
                    except Exception as error:
                        self.finished.emit(generation, '', str(error))
                    finally:
                        session.stop()
                        self._sessions.discard(session)
                threading.Thread(target=execute, daemon=True).start()
            def current_definition():
                try:
                    if app.package:
                        self.packages.load_verified(app)
                    return (not self._closed and generation == self._generation
                            and self.store.load(app.id).as_dict() == app.as_dict())
                except Exception:
                    return False
            token = ManagementControlPort(self.runtime).request_application(execution.as_dict(), flow, approved, current_definition)
            self._approval_tokens[app.id] = token
        except Exception as error:
            self._run_app = self._selected
            self._state, self._error = 'error', str(error)
            self._hold('application', False)
            if delivery is not None:
                bridge, view_generation, request_id = delivery
                bridge.deliver(view_generation, request_id, '', str(error))
        self.changed.emit()

    @Slot(int, str, str)
    def _finish(self, generation, result, error):
        if self._closed or generation != self._generation:
            return
        self._state, self._result, self._error = ('error' if error else 'done'), result, error
        self._hold('application', False)
        delivery = self._deliveries.pop(generation, None)
        if delivery is not None:
            bridge, view_generation, request_id = delivery
            bridge.deliver(view_generation, request_id, result, error)
        self.changed.emit()

    def _ensure_application(self, app, restore=False):
        entry = {'id': 'main', 'adapter': 'qt-quick'} if app.package else None
        metadata = {}
        if app.package:
            try:
                manifest = self.packages.load_verified(app)['manifest']
                metadata = dict(component_type=manifest['id'], version=manifest['version'])
            except PlatformError:
                pass  # Broken packages retain their identity and remain removable.
        return self.runtime.ensure_application(app, restore=restore, entry_view=entry,
            data_directory=self.application_data_directory(app.id), **metadata,
            factory=lambda: self._create_application(app, entry))

    def _create_application(self, app, entry):
        epoch = uuid4().hex
        self._component_epochs[app.id] = epoch
        def stopped():
            self._backend_component_stopped(app.id)
            self.applicationStopped.emit(app.id, epoch)
        callbacks = self.packages.load_verified(app)['manifest'].get('callbacks', {}) if app.package else {}
        return Application(definition=app, entry_view=entry,
            on_start=lambda: self._backend_component_started(app.id), on_stop=stopped,
            callbacks=callbacks, on_callback=lambda command, params: self._backend_callback(app.id, command, params))

    def _stop_application(self, application_id):
        try:
            self.runtime.stop_application(application_id)
        except PlatformError as error:
            if error.code != 'unknown_application':
                raise
        self._runtime_stopped(application_id)

    @Slot(str, str)
    def _runtime_stopped(self, application_id, epoch=None):
        if epoch is not None and self._active_epochs.get(application_id) != epoch:
            return  # A queued stop from an older run cannot close a reopened view.
        view = self._views.get(application_id)
        if view is not None:
            view.set_active(False)
        if self._run_app == application_id:
            self._deliveries.pop(self._generation, None)
            self._generation += 1
        token = self._approval_tokens.pop(application_id, None)
        if token:
            ManagementControlPort(self.runtime).cancel_approval(token)
            self._hold('application', False)
        for session in tuple(self._sessions):
            if session.application.id == application_id:
                session.stop()
                self._sessions.discard(session)
        if self._run_app == application_id:
            self._state, self._result, self._error = 'idle', '', ''
            self._hold('application', False)
        self.changed.emit()

    @Slot()
    def revoke(self):
        try:
            self._local_input()
            app = self.store.load(self._selected)
            self._clear_backend_intent(app.id)
            self._stop_application(app.id)
            self._ensure_application(app, restore=True)
            self.runtime.revoke_application_authority(app.id)
            self._notice = ''
            self._feedback = '已撤销此应用的全部授权；再次执行时需重新确认'
            self._update_views()
        except Exception as error:
            self._notice = '撤销授权失败：' + str(error)
        self.changed.emit()

    @Slot()
    def remove(self):
        try:
            self._local_input()
            app = self.store.load(self._selected)
            self._clear_backend_intent(app.id)
            self._stop_application(app.id)
            self._ensure_application(app, restore=True)
            # Remove authority before deleting anything. A partial failure can
            # retain a visible definition/reference, but never hidden grants.
            self.runtime.revoke_application_authority(app.id)
            self.store.delete(app.id)
            try:
                self.runtime.unregister_application_principal(app.id)
            except Exception:
                self.store.save(app)
                raise
            view = self._views.pop(app.id, None)
            if view is not None:
                view.close()
            self._selected = ''
            if app.package:
                try:
                    self.packages.remove(app)
                except Exception as error:
                    raise PlatformError('application_cleanup_failed', '应用已停用且授权已撤销，残留代码清理失败：' + str(error)) from error
            self._notice = ''
            self._feedback = '应用已移除，授权和实例引用已清理'
        except Exception as error:
            self._notice = '移除应用失败：' + str(error)
        self.changed.emit()

    def close(self):
        self._closed = True
        for definition in self._definitions():
            self._stop_application(definition['applicationId'])
        self._generation += 1
        for session in tuple(self._sessions):
            session.stop()
        self._sessions.clear()
        for token in tuple(self._approval_tokens.values()):
            ManagementControlPort(self.runtime).cancel_approval(token)
        self._approval_tokens.clear()
        self._deliveries.clear()
        for view in self._views.values():
            view.close()
        self._views.clear()
        self._view_parent = None
        self._hold('application', False)

    def application_data_directory(self, application_id):
        if self.store is None:
            raise PlatformError('application_storage_unavailable', '应用存储目录尚未就绪')
        return self.store.directory.parent / 'application-data' / application_id

    @Slot(str)
    def installDirectory(self, location):
        app = None
        committed = False
        try:
            self._local_input()
            if self.packages is None:
                raise PlatformError('application_storage_unavailable', '应用存储目录尚未就绪')
            if self.busy:
                raise PlatformError('application_busy', '请等待当前应用操作完成')
            path = QUrl(location).toLocalFile() if location.startswith('file:') else location
            app = self.packages.install(path)
            verified = self.packages.load_verified(app)
            package_id = verified['manifest']['id']
            for existing in self._definitions():
                previous = ApplicationDefinition.from_dict(existing)
                if previous.package:
                    try:
                        previous_id = self.packages.load_verified(previous)['manifest']['id']
                    except PlatformError:
                        continue  # A broken old package cannot block unrelated installs.
                    if previous_id == package_id:
                        raise PlatformError('application_exists', '此应用已安装，当前版本暂不支持就地更新')
            self._ensure_application(app)
            try:
                self.runtime.register_application_bindings(app.id, [])
                self.store.save(app)
                committed = True
            except Exception:
                self.runtime.unregister_application_principal(app.id)
                raise
            if self._selected and not self._background_enabled(self._selected):
                self._stop_application(self._selected)
            self._selected = app.id
            self._notice, self._feedback = '', '应用已安装，请在“组件连接 / 权限”中连接所需能力'
            self._update_views()
        except Exception as error:
            if app is not None and not committed:
                self.packages.remove(app)
            self._notice = str(error)
        self.changed.emit()

    @Slot(str)
    def updateDirectory(self, location):
        self.updateApplication(self._selected, location)

    @Slot(str, str)
    def updateApplication(self, identity, location):
        candidate = None
        try:
            self._local_input()
            if self.busy or identity in self._package_updates:
                raise PlatformError('application_busy', '请等待当前应用操作完成')
            previous = self.store.load(identity)
            old = self.packages.load_verified(previous)
            path = QUrl(location).toLocalFile() if location.startswith('file:') else location
            candidate = self.packages.install(path)
            verified = self.packages.load_verified(candidate)
            if old['manifest']['id'] != verified['manifest']['id']:
                raise PlatformError('application_package_mismatch', '更新包不是当前应用')
            candidate.id = previous.id
            candidate.config = previous.config
            candidate.flows, candidate.pages = previous.flows, previous.pages
            for alias, binding in previous.bindings.items():
                if alias not in verified['requires']:
                    continue
                candidate.bindings[alias] = binding
                try:
                    self._verify_binding(candidate, alias)
                except PlatformError as error:
                    if error.code != 'application_binding_unavailable':
                        raise
                    candidate.bindings.pop(alias)
            candidate = ApplicationDefinition.from_dict(candidate.as_dict())
            enabled = self._background_enabled(identity)
            self._package_updates[identity] = (previous, candidate)
            self._stop_application(identity)
            if enabled:
                self._set_backend_intent(identity, True)
            view = self._views.pop(identity, None)
            if view is not None:
                view.close()
            runner = self._backends.get(identity)
            if runner is not None and not runner.stopped.is_set():
                def wait_for_stop():
                    runner.stopped.wait()
                    self.updatePrepared.emit(identity)
                threading.Thread(target=wait_for_stop, daemon=True, name='application-update').start()
                self._feedback = '正在停止旧版应用后台'
            else:
                self._commit_package_update(identity)
            candidate = None
        except Exception as error:
            if candidate is not None:
                self._package_updates.pop(candidate.id, None)
                self.packages.remove(candidate)
            self._notice = str(error)
        self.changed.emit()

    @Slot(str)
    def _commit_package_update(self, identity):
        transaction = self._package_updates.get(identity)
        if transaction is None:
            return
        previous, candidate = transaction
        committed = False
        try:
            if self._closed or self.store.load(identity).as_dict() != previous.as_dict():
                raise PlatformError('stale_application', '应用已关闭或定义已变化，更新未应用')
            runner = self._backends.get(identity)
            if runner is not None and runner.stop_error:
                raise PlatformError('application_stop_failed', runner.stop_error)
            self.packages.load_verified(candidate)
            self.runtime.register_application_bindings(identity, [v['instanceId'] for v in candidate.bindings.values()])
            try:
                self.store.save(candidate)
            except Exception:
                self.runtime.register_application_bindings(identity, [v['instanceId'] for v in previous.bindings.values()])
                raise
            committed = True
            self._package_updates.pop(identity)
            self._backends.pop(identity, None)
            self._ensure_application(candidate, restore=True)
            self.packages.remove(previous)
            self._notice, self._feedback = '', '应用已更新；新增能力须连接并授权'
            if self._background_enabled(identity):
                try:
                    self.runtime.start_application(identity)
                except Exception as error:
                    self._backend_errors[identity] = str(error)
            self._update_views()
        except Exception as error:
            self._notice = str(error)
        finally:
            self._package_updates.pop(identity, None)
            if not committed:
                self.packages.remove(candidate)
            self.changed.emit()

    @staticmethod
    def _matches_requirement(status, operation, metadata, requirement):
        if (metadata.get('available', True) is False
                or metadata.get('applicationBinding') != 'instance'
                or metadata.get('access', 'read') != requirement['access']):
            return False
        if 'contract' in requirement:
            from ..contracts import contract_version
            return (metadata.get('provides') == requirement['contract']
                    and metadata.get('major', 1) == contract_version(requirement['contract']))
        return (status['componentType'] == requirement['componentType']
                and operation == requirement['operation']
                and metadata.get('major', 1) == requirement['major'])

    def _verify_binding(self, app, alias):
        verified = self.packages.load_verified(app)
        requirement = verified['requires'].get(alias)
        if requirement is None:
            raise PlatformError('application_alias_missing', alias)
        binding = app.bindings.get(alias)
        if binding is None:
            raise PlatformError('application_binding_missing', '请先连接组件能力：' + alias)
        status = self.runtime.status(binding['target'])
        metadata = status.get('description', {}).get('operations', {}).get(binding['operation'], {})
        if (not self._matches_requirement(status, binding['operation'], metadata, requirement)
                or status['installationId'] != binding['installationId']
                or status['instanceId'] != binding['instanceId']):
            raise PlatformError('application_binding_unavailable', '原组件连接已不可用，请重新选择：' + alias)
        semantic = capability(status['instanceId'], 'operation', binding['operation'], metadata)
        if status['state'] != 'running' or list(semantic) != list(binding['semantic']):
            raise PlatformError('application_binding_unavailable', '组件能力已变化，请重新选择：' + alias)
        return binding

    @Property(str, notify=changed)
    def connectionsJson(self):
        try:
            app = self.store.load(self._selected)
            if not app.package:
                return '[]'
            requirements = self.packages.load_verified(app)['requires']
            rows = []
            for alias, requirement in requirements.items():
                binding = app.bindings.get(alias)
                candidates = []
                for status in self.runtime.list_instances():
                    if status['state'] != 'running':
                        continue
                    for operation, metadata in status.get('description', {}).get('operations', {}).items():
                        if self._matches_requirement(status, operation, metadata, requirement):
                            label = status['manifest']['name'] + (' · 默认实例' if status.get('isDefault') else ' · 实例 ' + status['instanceId'][:8])
                            label += ' · ' + operation
                            preferred = status['componentType'] == requirement.get('preferredComponentType')
                            candidates.append(dict(instanceId=status['instanceId'], operation=operation,
                                                   label=label, preferred=preferred))
                candidates.sort(key=lambda item: not item['preferred'])
                selected, issue = -1, ''
                if binding:
                    try:
                        self._verify_binding(app, alias)
                        selected = next((index for index, candidate in enumerate(candidates)
                                         if candidate['instanceId'] == binding['instanceId']
                                         and candidate['operation'] == binding['operation']), -1)
                    except Exception:
                        issue = '原实例不可用，请重新选择'
                rows.append(dict(alias=alias, label=requirement.get('label', alias), contract=requirement.get('contract', ''), operation=requirement.get('operation', requirement.get('contract')), componentType=requirement.get('componentType', ''),
                                 candidates=candidates, selected=selected, issue=issue))
            return json.dumps(rows, ensure_ascii=False)
        except Exception:
            return '[]'

    @Slot()
    def refreshConnections(self):
        self.changed.emit()

    @Slot(str, str)
    @Slot(str, str, str)
    def bindInstance(self, alias, instance_id, operation=None):
        try:
            self._local_input()
            app = self.store.load(self._selected)
            requirement = self.packages.load_verified(app)['requires'].get(alias)
            if requirement is None:
                raise PlatformError('application_alias_missing', alias)
            status = self.runtime.status(instance_id)
            matches = [name for name, meta in status.get('description', {}).get('operations', {}).items()
                       if self._matches_requirement(status, name, meta, requirement)]
            if operation is None and len(matches) == 1:
                operation = matches[0]
            if status['instanceId'] != instance_id or operation not in matches:
                raise PlatformError('application_binding_unavailable', '请选择匹配的组件实例')
            self.runtime.start_application(app.id)
            handle = self.runtime.application_client(app.id).bind(instance_id, operation)
            candidate = dict(target=instance_id, instanceId=instance_id, installationId=status['installationId'],
                             operation=operation, semantic=list(handle.semantic))
            previous = dict(app.bindings)
            app.bindings[alias] = candidate
            self._verify_binding(app, alias)
            self._clear_backend_intent(app.id)
            self._stop_application(app.id)
            # Previously approved authority must not silently survive a changed
            # connection to another component instance or revision.
            self.runtime.revoke_application_authority(app.id)
            self.runtime.register_application_bindings(app.id, [item['instanceId'] for item in app.bindings.values()])
            try:
                self.store.save(app)
            except Exception:
                self.runtime.register_application_bindings(app.id, [item['instanceId'] for item in previous.values()])
                raise
            self._notice, self._feedback = '', '组件已连接；执行时将确认所需权限'
            self._update_views()
        except Exception as error:
            self._notice = str(error)
        self.changed.emit()

    @Slot(QObject)
    def attachView(self, parent):
        try:
            self._local_input()
            if self._view_parent is not parent:
                for view in self._views.values():
                    view.close()
                self._views.clear()
                self._view_parent = parent
            self._update_views()
        except Exception as error:
            self._notice = str(error)
            self.changed.emit()

    def _update_views(self):
        for identity, view in self._views.items():
            if identity != self._selected or not self._presentation_active or self._closed:
                view.set_active(False)
        if not self._selected or self._view_parent is None or self._closed:
            return
        try:
            import shiboken6
            if not shiboken6.isValid(self._view_parent):
                return
            app = self.store.load(self._selected)
            if not app.package:
                return
            verified = self.packages.load_verified(app)
            if app.id not in self._views:
                from .application_view import ApplicationView
                self._views[app.id] = ApplicationView(self, app, verified['entry'], self._view_parent)
            if self._presentation_active:
                if self.runtime.status(app.id)['state'] != 'running':
                    self._runtime_stopped(app.id)
                self._ensure_application(app, restore=True)
                self.runtime.start_application(app.id)
                self._active_epochs[app.id] = self._component_epochs.get(app.id)
            self._views[app.id].set_active(self._presentation_active)
        except Exception as error:
            self._stop_application(self._selected)
            self._notice = '应用界面不可用：' + str(error)

    def set_presentation_active(self, active):
        self._presentation_active = bool(active)
        if not active and self._selected and not self._background_enabled(self._selected):
            self._stop_application(self._selected)
        self._update_views()

    def call_alias(self, bridge, alias, params, request_id):
        self._local_input()
        if (not self._presentation_active
                or self.runtime.status(bridge.application_id)['state'] != 'running'
                or bridge.application_id != self._selected
                or self._views.get(self._selected) is None
                or self._views[self._selected].bridge is not bridge):
            raise PlatformError('application_inactive', '此应用当前未打开')
        app = self.store.load(self._selected)
        self._verify_binding(app, alias)
        self._begin(app, None, params, alias=alias,
                    delivery=(bridge, bridge.generation, request_id))
