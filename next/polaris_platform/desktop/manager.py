"""Trusted local management component. Runtime access never reaches plugin views."""
import json
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer
from .presentation import Presentation
from .window import GuiDispatcher
from ..protocol import PlatformError


class ManagerBridge(QObject):
    changed = Signal()
    completed = Signal(object)
    installationReady = Signal()
    installationCancelled = Signal()
    planReady = Signal()
    planCancelled = Signal()
    approvalFinished = Signal(str, str)
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self._data, self._permissions, self._plan_json = '[]', '[]', '[]'
        self._notice = ''
        self._installation_plan = None
        self._busy, self._closed = False, False
        self._worker, self._pending_plan = None, None
        self._pending_user_request = []
        self._approvals = {}
        self.completed.connect(self._complete)
        self.approvalFinished.connect(self._finish_approval)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        from PySide6.QtGui import QGuiApplication
        self.moveToThread(QGuiApplication.instance().thread())

    @Property(str, constant=True)
    def aboutJson(self):
        from .. import metadata
        return json.dumps({name: getattr(metadata, name) for name in (
            'APP_NAME', 'DISPLAY_VERSION', 'AUTHOR', 'PROJECT_URL', 'CODE_LICENSE', 'ARTWORK_LICENSE',
            'ARTWORK_CREDIT', 'ARTWORK_URL')}, ensure_ascii=False)

    @Property(str, notify=changed)
    def dataJson(self): return self._data
    @Property(str, notify=changed)
    def permissionsJson(self): return self._permissions
    @Property(str, notify=changed)
    def planJson(self): return self._plan_json
    @Property(str, notify=changed)
    def planSubject(self): return self._pending_plan.get('subject', '') if self._pending_plan else ''
    @Property(str, notify=changed)
    def notice(self): return self._notice
    @Property(str, notify=changed)
    def installationPrompt(self):
        plan = self._installation_plan
        if not plan: return ''
        return ('覆盖安装' if plan['action'] == 'replace' else '卸载') + '“' + plan['name'] + '”？'

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    def submit(self, fn, user_input=False):
        if self._closed: return
        if self._busy:
            if user_input: self._pending_user_request.append(fn)
            return
        self._busy = True
        self.changed.emit()
        def work():
            try:
                result = fn()
                snapshot = self.runtime.snapshot()
                decisions = self.runtime.authorization.decisions()
                if not self._closed:
                    self.completed.emit((snapshot, decisions, result, None))
            except Exception as exc:
                if not self._closed:
                    self.completed.emit((None, None, None, str(exc)))
        self._worker = threading.Thread(target=work, daemon=True, name='desktop-manager')
        self._worker.start()

    @Slot(object)
    def _complete(self, result):
        snapshot, decisions, value, error = result
        if isinstance(value, dict) and '_view_plan' in value:
            token = value['_view_plan'].get('approvalToken')
            if token and token not in self._approvals: value = None
        self._busy = False
        if error:
            self._notice = error
        elif isinstance(value, dict) and '_installation_plan' in value:
            self._installation_plan = value['_installation_plan']
            self._notice = ''
            self.installationReady.emit()
        elif isinstance(value, dict) and '_notice' in value:
            self._notice = value['_notice']
        elif isinstance(value, dict) and '_view_plan' in value:
            self.cancelView()
            self._pending_plan = value['_view_plan']
            self._plan_json = json.dumps(self._pending_plan['permissions'], ensure_ascii=False)
        elif value is not None:
            self._notice = json.dumps(value, ensure_ascii=False, default=str)[:1200]
        if snapshot is not None:
            records = [dict(item, name=item['manifest']['name'], manageable=item['id'] != getattr(self.runtime, 'management_component_id', 'manager') and item['id'] not in self.runtime.roles.values()) for item in snapshot]
            self._data = json.dumps(records, ensure_ascii=False, default=str)
            self._permissions = json.dumps(decisions, ensure_ascii=False)
            if self._pending_plan:
                source = next((row for row in snapshot if row['id'] == self._pending_plan['requester']), None)
                if source is None or source['state'] != 'running' or source['instance'] != self._pending_plan['requesterInstance']:
                    self.cancelView()
        self.changed.emit()
        if isinstance(value, dict) and '_view_plan' in value and self._pending_plan is not None:
            if all(row['authorized'] for row in self._pending_plan['permissions']):
                self.confirmView()
            else:
                self.planReady.emit()
        if self._pending_user_request and not self._busy:
            self.submit(self._pending_user_request.pop(0), user_input=True)

    @Slot()
    def quit(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance().quit()

    @Slot()
    def refresh(self): self.submit(lambda: None)

    @Slot(str, str)
    def lifecycle(self, target, action):
        self.submit(lambda: getattr(self.runtime, action + '_component')(target))

    def _installation_record(self, target):
        return next((row for row in self.runtime.export_installations() if row['manifest']['id'] == target), None)

    def _check_manageable(self, target, action='uninstall'):
        options = self.runtime.management_options(target) if hasattr(self.runtime, 'management_options') else {}
        if options.get(action) is False or target == getattr(self.runtime, 'management_component_id', 'manager') or target in self.runtime.roles.values():
            raise ValueError('此组件需在退出后通过启动配置更改')

    def _installation_confirmation(self, record, action, **extra):
        target = record['manifest']['id']
        self._check_manageable(target, 'replace' if action == 'replace' else 'uninstall')
        return {'_installation_plan': dict(action=action, target=target,
                name=record['manifest']['name'], identity=record['installationId'],
                directory=record.get('directory'), **extra)}

    @Slot(str)
    def loadDirectory(self, path):
        from PySide6.QtCore import QUrl
        from pathlib import Path
        local = str(Path(QUrl(path).toLocalFile() if path.startswith('file:') else path).resolve())
        def load():
            manifest = json.loads((Path(local) / 'manifest.json').read_text(encoding="utf-8"))
            existing = self._installation_record(manifest['id'])
            if existing:
                return self._installation_confirmation(existing, 'replace', path=local, manifest=manifest)
            self.runtime.install_directory(local)
            return {'_notice': '已安装“' + manifest['name'] + '”'}
        self.submit(load, user_input=True)

    @Slot(str)
    def prepareUninstall(self, target):
        def prepare():
            record = self._installation_record(target)
            if record is None: raise ValueError('组件已卸载，请重新选择')
            return self._installation_confirmation(record, 'uninstall')
        self.submit(prepare, user_input=True)

    @Slot()
    def cancelInstallation(self):
        self._installation_plan = None
        self.installationCancelled.emit()
        self.changed.emit()

    @Slot()
    def confirmInstallation(self):
        plan = self._installation_plan
        if plan is None: return
        self.cancelInstallation()
        def execute():
            current = self._installation_record(plan['target'])
            if (current is None or current['installationId'] != plan['identity']
                    or current.get('directory') != plan['directory']):
                raise ValueError('安装信息已变化，请重新选择')
            self._check_manageable(plan['target'], 'replace' if plan['action'] == 'replace' else 'uninstall')
            if plan['action'] == 'replace':
                from pathlib import Path
                manifest = json.loads((Path(plan['path']) / 'manifest.json').read_text(encoding="utf-8"))
                if manifest != plan['manifest']: raise ValueError('组件目录已变化，请重新加载')
                self.runtime.install_directory(plan['path'], replace=True)
                return {'_notice': '已覆盖安装“' + plan['name'] + '”'}
            self.runtime.uninstall_component(plan['target'])
            return {'_notice': '已卸载“' + plan['name'] + '”'}
        self.submit(execute, user_input=True)

    @Slot(str, str, str, str, bool, bool)
    def permission(self, requester, target, name, kind, background, allow):
        def change():
            method = self.runtime.grant if allow else self.runtime.revoke
            method(requester, target, name, kind=kind, background=background)
            return {'result': '已授权' if allow else '已撤销'}
        self.submit(change)

    @Slot(str, str, str, str)
    def invoke(self, requester, target, operation, params):
        def call():
            values = json.loads(params or '{}')
            if not isinstance(values, dict): raise ValueError('参数应为JSON对象')
            return self.runtime.client(requester).call(target, operation, values,
                                                       context=self.runtime.user_context(requester))
        self.submit(call)

    @Slot(str, str, str)
    def componentPermission(self, requester, target, mode):
        if mode not in ('none', 'read', 'all'):
            return
        record = self.runtime.status(target)
        description = record.get('description', {})
        installation = record['installation']
        capabilities = [(kind, name, metadata) for kind, section in
                        (('operation', 'operations'), ('event', 'events'))
                        for name, metadata in description.get(section, {}).items()]
        def change():
            current = self.runtime.status(target)
            if (current['installation'] != installation or any(
                    current.get('description', {}).get('operations' if kind == 'operation' else 'events', {}).get(name) != metadata
                    for kind, name, metadata in capabilities)):
                raise ValueError('组件能力已变化，请重新选择')
            for kind, name, metadata in capabilities:
                allow = mode == 'all' or mode == 'read' and metadata.get('access', 'read') == 'read'
                method = self.runtime.grant if allow else self.runtime.revoke
                method(requester, target, name, kind=kind, background=False)
            return {'_notice': '已更新组件权限：' + {'none': '禁止', 'read': '只读', 'all': '允许全部'}[mode]}
        self.submit(change, user_input=True)

    def _make_plan(self, requester, target, action):
        records = {row['id']: row for row in self.runtime.snapshot()}
        view = next((view for view in records[target]['description'].get('views', [])
                     if any(item['operation'] == action for item in view.get('actions', []))), None)
        if view is None: raise ValueError('此视图操作已经撤回')
        descriptor = next(item for item in view['actions'] if item['operation'] == action)
        permissions = [{'target': target, 'name': action}] + descriptor.get('permissions', [])
        return self._permission_plan(records, requester, target, action, permissions)

    def _permission_plan(self, records, requester, target, action, permissions, params=None, plan_type='view'):
        from ..protocol import capability
        scope = self.runtime.authorization.scope(requester)
        rows, seen = [], set()
        for permission in permissions:
            identity, name, kind = permission['target'], permission['name'], permission.get('kind', 'operation')
            if (identity, name, kind) in seen: continue
            seen.add((identity, name, kind))
            row = records[identity]
            metadata = row['description']['operations' if kind == 'operation' else 'events'][name]
            key = list(capability(row['installation'], kind, name, metadata))
            rows.append({'target': identity, 'title': row['manifest']['name'], 'name': name,
                         'access': metadata.get('access', 'read'), 'kind': kind, 'key': key,
                         'authorized': tuple(key) in scope})
        return {'requester': requester, 'requesterInstallation': records[requester]['installation'],
                'requesterInstance': records[requester]['instance'],
                'subject': records[requester]['manifest']['name'] + ' · ' + requester,
                'target': target, 'action': action, 'params': params or {}, 'type': plan_type, 'permissions': rows}

    def _make_mount_plan(self, requester, target, view_id):
        records = {row['id']: row for row in self.runtime.snapshot()}
        descriptor = next((item for item in records[target]['description'].get('views', [])
                           if item.get('id') == view_id and item.get('adapter') == 'qt-quick-item'), None)
        if descriptor is None: raise ValueError('此视图已经撤回')
        permissions = [{'target': requester, 'name': 'mount'},
                       {'target': target, 'name': descriptor.get('create', 'create_view')},
                       {'target': target, 'name': descriptor.get('release', 'release_view')}]
        for view in records[requester]['description'].get('views', []):
            for action in view.get('actions', []):
                if action['operation'] == 'show': permissions += action.get('permissions', [])
        permissions += [dict(item, target=item.get('target', target)) for item in descriptor.get('permissions', [])]
        params = {'target': target, 'view': view_id, 'descriptor': descriptor}
        plan = self._permission_plan(records, requester, requester, 'mount', permissions, params, 'mount')
        plan.update(provider=target, viewId=view_id)
        return plan

    def request_mount(self, requester, target, view_id, on_finished=None):
        token = uuid.uuid4().hex
        instance = self.runtime.status(requester)['instance']
        self._approvals[token] = on_finished
        def prepare():
            try:
                if token not in self._approvals:
                    return None
                plan = self._make_mount_plan(requester, target, view_id)
                if plan['requesterInstance'] != instance:
                    raise ValueError('发起组件已重新启动，请重新选择')
                plan['approvalToken'] = token
                return {'_view_plan': plan}
            except Exception:
                self.approvalFinished.emit(token, 'failed')
                raise
        self.submit(prepare, user_input=True)
        return token

    @Slot(str, str, str)
    def prepareMount(self, requester, target, view_id):
        self.request_mount(requester, target, view_id)

    @Slot(str, str)
    def _finish_approval(self, token, status):
        if token not in self._approvals: return
        callback = self._approvals.pop(token)
        if callback: callback(status)

    @Slot()
    def cancelView(self):
        plan, self._pending_plan = self._pending_plan, None
        if plan and plan.get('approvalToken'):
            self._finish_approval(plan['approvalToken'], 'cancelled')
        self._plan_json = '[]'
        self.changed.emit()
        if plan: self.planCancelled.emit()

    def cancel_all(self):
        self.cancelView()
        self.cancelInstallation()
        self._pending_user_request.clear()
        for token in tuple(self._approvals):
            self._finish_approval(token, 'cancelled')

    @Slot(str, str, str)
    def prepareView(self, requester, target, action):
        self.submit(lambda: {'_view_plan': self._make_plan(requester, target, action)}, user_input=True)

    @Slot()
    def confirmView(self):
        plan = self._pending_plan
        if plan is None: return
        def execute():
            token = plan.get('approvalToken')
            outcome = 'failed'
            try:
                if token and token not in self._approvals:
                    return None
                if plan.get('type') == 'mount':
                    current = self._make_mount_plan(plan['requester'], plan['provider'], plan['viewId'])
                else:
                    current = self._make_plan(plan['requester'], plan['target'], plan['action'])
                if (current['requesterInstallation'] != plan['requesterInstallation']
                    or current['requesterInstance'] != plan['requesterInstance']
                    or [row['key'] for row in current['permissions']] != [row['key'] for row in plan['permissions']]):
                    raise ValueError('能力或发起实例已变化，请重新选择')
                client = self.runtime.client(plan['requester'])
                if client.instance != plan['requesterInstance']:
                    raise ValueError('发起组件已重新启动，请重新选择')
                for row in current['permissions']:
                    if not row['authorized']:
                        self.runtime.grant(plan['requester'], row['target'], row['name'], kind=row['kind'])
                if token and token not in self._approvals:
                    return None
                result = client.call(plan['target'], plan['action'], current['params'],
                                     context=self.runtime.user_context(plan['requester']))
                outcome = 'confirmed'
                return result
            finally:
                if token: self.approvalFinished.emit(token, outcome)
        self._pending_plan = None
        self.submit(execute, user_input=True)



class Manager(Presentation):
    """Trusted local management component, with its own native management view."""
    source, title, size = 'Manager.qml', 'Polaris · 组件管理', (1040, 760)
    def __init__(self, runtime=None):
        super().__init__()
        self._cleanup_host = None
        self.dependencies = []
        self.views = [{'id': 'main', 'title': self.title, 'adapter': 'qt-quick', 'actions': [
            {'label': '显示', 'operation': 'show', 'permissions': []},
            {'label': '隐藏', 'operation': 'hide', 'permissions': []}]}]
        self.runtime = runtime
        self._gui = GuiDispatcher()
        self._view = None
        self.bridge = ManagerBridge(runtime) if runtime is not None else None

    def start(self, port):
        if self.runtime is not None: self.runtime.management_component_id = port.id
        super().start(port)
        if self.bridge is None and self.runtime is not None:
            self.bridge = self._gui.run(lambda: ManagerBridge(self.runtime))
        if self.bridge:
            self._gui.run(self.bridge.timer.start)
            self.bridge.refresh()

    def local_management_control(self):
        return self if self.running else None

    def request_mount(self, requester, target, view_id, on_finished=None):
        if not self.running or self.bridge is None:
            raise PlatformError('management_unavailable', '组件管理未运行')
        self.show()
        return self._gui.run(lambda: self.bridge.request_mount(requester, target, view_id, on_finished))

    def report_notice(self, message):
        def update():
            if self.bridge is not None:
                self.bridge._notice = str(message)
                self.bridge.changed.emit()
        self._gui.run(update)

    def refresh(self):
        if self.bridge is not None:
            self._gui.run(self.bridge.refresh)

    def status(self, context=None):
        state = self._gui.run(lambda: {'available': self._view is not None,
                                       'visible': self._view.isVisible() if self._view else False})
        return dict(state, running=self.running)

    def describe(self):
        result = super().describe()
        result['view_state'] = dict(self._view_state)
        return result

    def show(self, context=None):
        if not self.running:
            raise PlatformError('component_unavailable', '组件未运行')
        def display():
            if self._view is None:
                from pathlib import Path
                from PySide6.QtQuick import QQuickView
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QGuiApplication
                view = QQuickView()
                view.setTitle(self.title)
                view.setResizeMode(QQuickView.SizeRootObjectToView)
                view.rootContext().setContextProperty('manager', self.bridge)
                view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / self.source)))
                if view.status() == QQuickView.Error:
                    errors = '\n'.join(error.toString() for error in view.errors())
                    import shiboken6
                    shiboken6.delete(view)
                    raise PlatformError('view_error', errors)
                view.resize(*self.size)
                view.closing.connect(self._native_closed)
                self._view = view
            self._view.show()
            self._view.raise_()
        self._gui.run(display)
        self._view_state = self.status()
        return dict(self._view_state)

    @Slot()
    def _native_closed(self):
        self._view_state.update(visible=False)
        if self.bridge: self.bridge.cancel_all()

    def hide(self, context=None):
        if self.bridge: self._gui.run(self.bridge.cancel_all)
        if self._view: self._gui.run(self._view.hide)
        self._view_state = self.status()
        return dict(self._view_state)

    def stop(self):
        bridge = self.bridge
        if bridge:
            bridge._closed = True
            self._gui.run(bridge.cancel_all)
            self._gui.run(bridge.timer.stop)
            if bridge._worker and bridge._worker.is_alive() and bridge._worker is not threading.current_thread():
                bridge._worker.join(2)
        def dispose():
            import shiboken6
            if self._view:
                self._view.close()
                shiboken6.delete(self._view)
                self._view = None
            if bridge: shiboken6.delete(bridge)
        self._gui.run(dispose)
        self.bridge = None
        super().stop()


def create_manager(runtime=None):
    return Manager(runtime)
