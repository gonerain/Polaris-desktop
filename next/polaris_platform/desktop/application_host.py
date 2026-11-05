"""Trusted desktop host for application definitions and explicit local input."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Property
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QThread

from ..application import Application, ApplicationStore
from ..protocol import PlatformError
from .management_control import ManagementControlPort


class ApplicationHost(QObject):
    changed = Signal()
    finished = Signal(int, str, str)

    def __init__(self, runtime, hold=None):
        super().__init__()
        self.runtime = runtime
        self.store = None
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

    def configure(self, directory):
        self.store = ApplicationStore(Path(directory) / 'applications') if directory is not None else None
        self._closed = False
        if self.store:
            for definition in self._definitions():
                app = Application.from_dict(definition)
                try:
                    self.runtime.register_application_principal(app.id, restore=True)
                    self.runtime.register_application_bindings(app.id, [binding['instanceId'] for binding in app.bindings.values()])
                except PlatformError as error:
                    # Definitions and existing references remain intact; the
                    # unavailable binding is reported when this app executes.
                    self._notice = app.title + ': ' + error.message
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
            self._selected = application_id
            self._notice = ''
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
            app = Application.from_dict(json.loads(source))
            # Validate entirely before writing or registering any principal.
            if any(item['applicationId'] == app.id for item in self.store.list()):
                raise PlatformError('application_exists', '此应用身份已存在，请使用新的 applicationId')
            try:
                self.runtime.application_client(app.id)
            except PlatformError as error:
                if error.code != 'unknown_application':
                    raise
            else:
                raise PlatformError('application_identity_reserved', '此应用身份已登记，不能通过导入接管')
            registered = False
            try:
                self.runtime.register_application_principal(app.id)
                registered = True
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
            if self.busy:
                self._notice = '正在执行：' + self._run_title
                self.changed.emit()
                return
            app = self.store.load(self._selected)
            params = json.loads(params_json)
            if not isinstance(params, dict):
                raise PlatformError('invalid_application_input', '输入应为对象')
            if flow not in app.flows:
                raise PlatformError('application_flow_missing', flow)
            self.runtime.register_application_principal(app.id)
            self._generation += 1
            generation = self._generation
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
                    session = app.open(self.runtime.application_client(app.id),
                                       self.runtime.application_context(app.id), self.runtime.status)
                except Exception as error:
                    self.finished.emit(generation, '', str(error))
                    return
                self._sessions.add(session)
                self._state = 'running'
                self.changed.emit()
                def execute():
                    try:
                        result = session.run(flow, params)
                        self.finished.emit(generation, json.dumps(result, ensure_ascii=False, indent=2), '')
                    except Exception as error:
                        self.finished.emit(generation, '', str(error))
                    finally:
                        session.stop()
                        self._sessions.discard(session)
                threading.Thread(target=execute, daemon=True).start()
            def current_definition():
                try:
                    return (not self._closed and generation == self._generation
                            and self.store.load(app.id).as_dict() == app.as_dict())
                except Exception:
                    return False
            token = ManagementControlPort(self.runtime).request_application(app.as_dict(), flow, approved, current_definition)
            self._approval_tokens[app.id] = token
        except Exception as error:
            self._run_app = self._selected
            self._state, self._error = 'error', str(error)
            self._hold('application', False)
        self.changed.emit()

    @Slot(int, str, str)
    def _finish(self, generation, result, error):
        if self._closed or generation != self._generation:
            return
        self._state, self._result, self._error = ('error' if error else 'done'), result, error
        self._hold('application', False)
        self.changed.emit()

    def _stop_application(self, application_id):
        if self._run_app == application_id:
            self._generation += 1
        token = self._approval_tokens.pop(application_id, None)
        if token:
            ManagementControlPort(self.runtime).cancel_approval(token)
        for session in tuple(self._sessions):
            if session.application.id == application_id:
                session.stop()
                self._sessions.discard(session)
        if self._run_app == application_id:
            self._state, self._result, self._error = 'idle', '', ''
            self._hold('application', False)

    @Slot()
    def revoke(self):
        try:
            self._local_input()
            app = self.store.load(self._selected)
            self._stop_application(app.id)
            self.runtime.register_application_principal(app.id, restore=True)
            self.runtime.revoke_application_authority(app.id)
            self._notice = ''
            self._feedback = '已撤销此应用的全部授权；再次执行时需重新确认'
        except Exception as error:
            self._notice = '撤销授权失败：' + str(error)
        self.changed.emit()

    @Slot()
    def remove(self):
        try:
            self._local_input()
            app = self.store.load(self._selected)
            self._stop_application(app.id)
            self.runtime.register_application_principal(app.id, restore=True)
            # Remove authority before deleting anything. A partial failure can
            # retain a visible definition/reference, but never hidden grants.
            self.runtime.revoke_application_authority(app.id)
            self.store.delete(app.id)
            try:
                self.runtime.unregister_application_principal(app.id)
            except Exception:
                self.store.save(app)
                raise
            self._selected = ''
            self._notice = ''
            self._feedback = '应用已移除，授权和实例引用已清理'
        except Exception as error:
            self._notice = '移除应用失败：' + str(error)
        self.changed.emit()

    def close(self):
        self._closed = True
        self._generation += 1
        for session in tuple(self._sessions):
            session.stop()
        self._sessions.clear()
        for token in tuple(self._approval_tokens.values()):
            ManagementControlPort(self.runtime).cancel_approval(token)
        self._approval_tokens.clear()
        self._hold('application', False)
