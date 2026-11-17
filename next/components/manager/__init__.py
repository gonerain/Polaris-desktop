"""Trusted local management component. Runtime access never reaches plugin views."""
import json
import threading
import unicodedata
from pathlib import Path
import uuid
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QUrl
from polaris_platform.desktop.presentation import Presentation
from polaris_platform.desktop.qt_ports import GuiDispatcher
from polaris_platform.protocol import PlatformError


class ManagerBridge(QObject):
    changed = Signal()
    sourcesChanged = Signal()
    dataChanged = Signal()
    completed = Signal(object)
    instanceCreated = Signal(str)
    installationReady = Signal()
    installationCancelled = Signal()
    planReady = Signal()
    planCancelled = Signal()
    approvalFinished = Signal(str, str)
    applicationPermissionFinished = Signal(str, str, str)
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self._data, self._permissions, self._plan_json = '[]', '[]', '[]'
        self._notice = ''
        self._notice_error = False
        self._sources_json = '[]'
        self.defaults = None
        self._gui = GuiDispatcher()
        self._installation_plan = None
        self._busy, self._closed, self._polling = False, False, False
        self._worker, self._pending_plan = None, None
        self._pending_user_request = []
        self._pending_refresh = False
        self._approvals = {}
        self._application_checks = {}
        self.completed.connect(self._complete)
        self.approvalFinished.connect(self._finish_approval)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.poll)
        from PySide6.QtGui import QGuiApplication
        self.moveToThread(QGuiApplication.instance().thread())

    @Property(str, constant=True)
    def aboutJson(self):
        from polaris_platform import metadata
        return json.dumps({name: getattr(metadata, name) for name in (
            'APP_NAME', 'DISPLAY_VERSION', 'AUTHOR', 'PROJECT_URL', 'CODE_LICENSE', 'ARTWORK_LICENSE',
            'ARTWORK_CREDIT', 'ARTWORK_URL')}, ensure_ascii=False)

    @Property(str, notify=sourcesChanged)
    def sourcesJson(self): return self._sources_json

    @Slot(str, result=str)
    def normalizeMarketText(self, value):
        return unicodedata.normalize('NFKC', value).casefold()

    @Slot(str, str, result=str)
    def marketAssetUrl(self, directory, path):
        return QUrl.fromLocalFile(str(Path(directory) / path)).toString()

    @Slot(str, str, result=str)
    def marketReadme(self, directory, path):
        return (Path(directory) / path).read_text(encoding='utf-8')

    def _source_control(self):
        if self.runtime.status('sources')['state'] != 'running':
            raise ValueError('插件源管理未运行')
        provider = self.runtime.component_instance('sources')
        factory = getattr(provider, 'local_source_control', None)
        control = factory() if callable(factory) else None
        if control is None: raise ValueError('插件源管理未运行')
        return control

    def configure_defaults(self):
        from .defaults import DefaultInstallations, configured_sources
        specs = configured_sources(getattr(self.runtime, 'manager_config', {}))
        if not specs or not any(row['manifest']['id'] == 'sources' for row in self.runtime.export_installations()):
            return
        if self.runtime.status('sources')['state'] != 'running':
            return
        provider = self.runtime.component_instance('sources')
        control = getattr(provider, 'local_source_control', lambda: None)()
        if not hasattr(control, 'preset') or not hasattr(control, 'fetch_preset'):
            return
        self.defaults = DefaultInstallations(self.runtime, provider)
        self.defaults.changed.connect(self.refresh)
        self.defaults.configure(specs)

    @Slot(str)
    def retryDefault(self, source_id):
        if self.defaults and source_id in self.defaults.specs:
            self.defaults.request(source_id, load_catalog=source_id in self.defaults.default_catalogs)

    @Slot(str)
    @Slot(str, str)
    def addSource(self, location, ref=''):
        def add():
            self._source_control().add(location.strip(), ref=ref.strip() or None)
            return {'_notice': '已添加插件源，请选择需要安装的插件'}
        self.submit(add, user_input=True)

    @Slot(str)
    def refreshSource(self, source_id):
        self.submit(lambda: (self._source_control().refresh(source_id), {'_notice': '插件源已刷新'})[1], user_input=True)

    @Slot(str, str)
    @Slot(str, str, str)
    def installSource(self, source_id, component_id, expected_revision=None):
        def install():
            control = self._source_control()
            revision = next(row['revision'] for row in control.sources() if row['id'] == source_id)
            if expected_revision is not None and revision != expected_revision:
                raise PlatformError('source_changed', '源目录已变化，请重新查看后安装')
            existing = self._installation_record(component_id)
            if existing:
                return self._installation_confirmation(existing, 'replace', sourceId=source_id, sourceRevision=revision)
            self._gui.run(lambda: control.install(source_id, component_id, **({'expected_revision': expected_revision} if expected_revision is not None else {})))
            return {'_notice': '插件已安装'}
        self.submit(install, user_input=True)

    @Property(str, notify=dataChanged)
    def dataJson(self): return self._data
    @Property(str, notify=changed)
    def permissionsJson(self): return self._permissions
    @Property(str, notify=changed)
    def planJson(self): return self._plan_json
    @Property(str, notify=changed)
    def planSubject(self): return self._pending_plan.get('subject', '') if self._pending_plan else ''
    @Property(bool, notify=changed)
    def authorizationPending(self): return self._pending_plan is not None
    @Property(str, notify=changed)
    def planType(self): return self._pending_plan.get('type', '') if self._pending_plan else ''
    @Property(str, notify=changed)
    def planRequester(self): return self._pending_plan.get('requester', '') if self._pending_plan else ''
    @Property(str, notify=changed)
    def notice(self): return self._notice
    @Property(bool, notify=changed)
    def noticeIsError(self): return self._notice_error

    @Slot()
    def dismissNotice(self):
        self._notice = ''
        self._notice_error = False
        self.changed.emit()
    @Property(str, notify=changed)
    def installationPrompt(self):
        plan = self._installation_plan
        if not plan: return ''
        if plan['action'] == 'destroy_instance':
            return '删除实例“' + plan['name'] + '”？实例授权将清理，本地数据文件保留。'
        return ('覆盖安装' if plan['action'] == 'replace' else '卸载') + '“' + plan['name'] + '”？'

    @Property(bool, notify=changed)
    def busy(self): return (self._busy and not self._polling) or bool(self._pending_user_request)

    def submit(self, fn, user_input=False, polling=False, include_sources=True):
        if self._closed: return
        if self._busy:
            if polling and include_sources:
                self._pending_refresh = True
            elif not polling and (user_input or self._polling):
                self._pending_user_request.append(fn)
                self.changed.emit()
            return
        self._busy, self._polling = True, polling
        self.changed.emit()
        def work():
            try:
                result = fn()
                snapshot = self.runtime.snapshot()
                decisions = self.runtime.authorization.decisions()
                sources = None
                if not self._closed and include_sources:
                    try:
                        control = self._source_control()
                        sources = control.sources()
                        for source in sources:
                            for collection in ('components', 'packages'):
                                for entry in source.get(collection, []):
                                    if collection == 'components' or entry['type'] == 'component':
                                        entry['installationOrigin'] = control.installation_origin(entry['manifest']['id'])
                    except (PlatformError, AttributeError, ValueError):
                        sources = []
                if not self._closed:
                    self.completed.emit((snapshot, decisions, result, None, sources))
            except Exception as exc:
                if not self._closed:
                    self.completed.emit((None, None, None, str(exc), None))
        self._worker = threading.Thread(target=work, daemon=True, name='desktop-manager')
        self._worker.start()

    @Slot(object)
    def _complete(self, result):
        snapshot, decisions, value, error, sources = result
        if sources is not None:
            rows = self.defaults.rows(sources) if self.defaults else sources
            source_json = json.dumps(rows, ensure_ascii=False, default=str)
            if source_json != self._sources_json:
                self._sources_json = source_json
                self.sourcesChanged.emit()
        if isinstance(value, dict) and '_view_plan' in value:
            token = value['_view_plan'].get('approvalToken')
            if token and token not in self._approvals: value = None
        self._busy, self._polling = False, False
        if error:
            self._notice = error
            self._notice_error = True
        elif isinstance(value, dict) and '_installation_plan' in value:
            self._installation_plan = value['_installation_plan']
            self._notice = ''
            self._notice_error = False
            self.installationReady.emit()
        elif isinstance(value, dict) and '_notice' in value:
            self._notice = value['_notice']
            self._notice_error = False
        elif isinstance(value, dict) and '_view_plan' in value:
            self.cancelView()
            self._pending_plan = value['_view_plan']
            self._pending_plan['requiresConfirmation'] = not all(row['authorized'] for row in self._pending_plan['permissions'])
            self._plan_json = json.dumps(self._pending_plan['permissions'], ensure_ascii=False)
        elif isinstance(value, dict) and '_application_permission_result' in value:
            outcome = value['_application_permission_result']
            self.applicationPermissionFinished.emit(outcome['requester'], outcome['status'], outcome['message'])
        elif value is not None:
            self._notice = json.dumps(value, ensure_ascii=False, default=str)[:1200]
            self._notice_error = False
        if snapshot is not None:
            records = []
            for item in snapshot:
                multiple = item['manifest'].get('instances', {}).get('mode') == 'multiple'
                default = item.get('isDefault', True)
                suffix = (' · 默认实例' if default else ' · 实例 ' + item.get('instanceId', item['id'])[:8]) if multiple else ''
                records.append(dict(item, name=item['manifest']['name'] + suffix,
                    canCreateInstance=multiple and item['manifest'].get('kind') != 'application',
                    manageable=default and item.get('manifest', {}).get('kind') != 'application'
                        and item['id'] != getattr(self.runtime, 'management_component_id', 'manager')
                        and item['id'] not in self.runtime.roles.values()))
            data_json = json.dumps(records, ensure_ascii=False, default=str)
            if data_json != self._data:
                self._data = data_json
                self.dataChanged.emit()
            self._permissions = json.dumps(decisions, ensure_ascii=False)
            if self._pending_plan:
                if self._pending_plan.get('type') == 'application':
                    try:
                        if self.runtime.application_client(self._pending_plan['requester']).instance != self._pending_plan['requesterInstance']:
                            self.cancelView()
                    except PlatformError:
                        self.cancelView()
                else:
                    source = next((row for row in snapshot if row['id'] == self._pending_plan['requester']), None)
                    if source is None or source['state'] != 'running' or source['instance'] != self._pending_plan['requesterInstance']:
                        self.cancelView()
        self.changed.emit()
        if isinstance(value, dict) and '_instance_created' in value:
            self.instanceCreated.emit(value['_instance_created'])
        if isinstance(value, dict) and '_view_plan' in value and self._pending_plan is not None:
            if all(row['authorized'] for row in self._pending_plan['permissions']):
                self.confirmView()
            else:
                self.planReady.emit()
        if self._pending_user_request and not self._busy:
            self.submit(self._pending_user_request.pop(0), user_input=True)
        elif self._pending_refresh and not self._busy:
            self._pending_refresh = False
            self.refresh()

    @Slot()
    def quit(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance().quit()

    @Slot()
    def refresh(self): self.submit(lambda: None, polling=True)

    @Slot()
    def poll(self): self.submit(lambda: None, polling=True, include_sources=False)

    @Slot(str, str)
    def lifecycle(self, target, action):
        self.submit(lambda: getattr(self.runtime, action + '_component')(target))

    @Slot(str)
    def createInstance(self, target):
        def create():
            source = self.runtime.status(target)
            if (source['manifest'].get('instances', {}).get('mode') != 'multiple'
                    or source['manifest'].get('kind') == 'application'):
                raise ValueError('此组件不支持新建实例')
            identity = self.runtime.create_instance(source['componentType'])
            try:
                self.runtime.start_instance(identity)
            except Exception as error:
                return {'_instance_created': identity, '_notice': '实例已创建，启动失败：' + str(error)}
            return {'_instance_created': identity, '_notice': '新实例已启动，请打开其界面配置'}
        self.submit(create, user_input=True)

    def _installation_record(self, target):
        return next((row for row in self.runtime.export_installations() if row['manifest']['id'] == target), None)

    def _check_manageable(self, target, action='uninstall'):
        if any(row['id'] == target and not row.get('isDefault', True)
               for row in self.runtime.snapshot()):
            raise ValueError('这是独立实例，不能作为组件安装卸载')
        if any(row['id'] == target and row.get('manifest', {}).get('kind') == 'application'
               for row in self.runtime.snapshot()):
            raise ValueError('请在扩展管理的应用页卸载应用')
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

    @Slot(str)
    def prepareDeleteInstance(self, target):
        def prepare():
            record = self.runtime.status(target)
            if record.get('isDefault', True):
                raise ValueError('默认实例不能单独删除')
            if record['state'] not in ('installed', 'stopped', 'failed'):
                raise ValueError('请先停止实例，再删除')
            return {'_installation_plan': dict(action='destroy_instance', target=record['instanceId'],
                name=record['manifest']['name'] + ' · ' + record['instanceId'][:8],
                identity=record['instanceId'], installationId=record['installationId'])}
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
            if plan['action'] == 'destroy_instance':
                current = self.runtime.status(plan['target'])
                if (current.get('isDefault', True) or current['instanceId'] != plan['identity']
                        or current['installationId'] != plan['installationId']):
                    raise ValueError('实例信息已变化，请重新选择')
                try:
                    self.runtime.destroy_instance(plan['target'])
                except PlatformError as error:
                    if error.code == 'instance_in_use':
                        raise ValueError('实例仍被引用或正在使用，请先解除引用并停止实例') from None
                    raise
                return {'_notice': '实例已删除，本地数据文件保留'}
            current = self._installation_record(plan['target'])
            if (current is None or current['installationId'] != plan['identity']
                    or current.get('directory') != plan['directory']):
                raise ValueError('安装信息已变化，请重新选择')
            self._check_manageable(plan['target'], 'replace' if plan['action'] == 'replace' else 'uninstall')
            if plan['action'] == 'replace' and 'sourceId' in plan:
                self._gui.run(lambda: self._source_control().install(plan['sourceId'], plan['target'], replace=True, expected_installation=plan['identity'], expected_revision=plan['sourceRevision']))
                return {'_notice': '插件已更新'}
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

    @Slot(str, str, str, str, str, str)
    def selectProvider(self, target, kind, name, alias, installation, consumer_installation):
        self.submit(lambda: self.runtime.select_provider(target, kind, name, alias, installation, consumer_installation),
                    user_input=True)

    def _make_plan(self, requester, target, action):
        records = {}
        for row in self.runtime.snapshot():
            records[row['id']] = row
            records[row.get('instanceId', row['id'])] = row
        view = next((view for view in records[target]['description'].get('views', [])
                     if any(item['operation'] == action for item in view.get('actions', []))), None)
        if view is None: raise ValueError('此视图操作已经撤回')
        descriptor = next(item for item in view['actions'] if item['operation'] == action)
        permissions = [{'target': target, 'name': action}] + descriptor.get('permissions', [])
        seen = set()
        def include_requirements(target, kind, name):
            if (target, kind, name) in seen:
                return
            seen.add((target, kind, name))
            meta = records[target]['description']['operations' if kind == 'operation' else 'events'][name]
            if not meta.get('available', True):
                raise ValueError(f"{name} 的依赖未就绪：{meta.get('reason')}")
            for binding in meta.get('bindings', {}).values():
                if binding['optional']:
                    continue
                endpoint = binding['endpoint']
                permissions.append(endpoint)
                include_requirements(endpoint['target'], endpoint['kind'], endpoint['name'])
        include_requirements(target, 'operation', action)
        plan = self._permission_plan(records, requester, target, action, permissions)
        plan['usesRequirements'] = bool(records[target]['description']['operations'][action].get('requires'))
        return plan

    def _permission_plan(self, records, requester, target, action, permissions, params=None, plan_type='view'):
        from polaris_platform.protocol import capability
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
        records = {}
        for row in self.runtime.snapshot():
            records[row['id']] = row
            records[row.get('instanceId', row['id'])] = row
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

    def _make_application_plan(self, definition, flow):
        from polaris_platform.application import Application
        from polaris_platform.protocol import capability
        app = Application.from_dict(definition)
        client = self.runtime.application_client(app.id)
        if flow not in app.flows:
            raise PlatformError('application_flow_missing', flow)
        scope = self.runtime.authorization.scope(app.id)
        rows, seen = [], set()
        def include(target, name, kind='operation', binding=None):
            if kind != 'operation':
                raise PlatformError('application_binding_unsupported', '当前应用流程不支持事件订阅')
            status = self.runtime.status(target)
            stable = status.get('instanceId', status['installation'])
            metadata = status['description']['operations' if kind == 'operation' else 'events'][name]
            if metadata.get('applicationBinding') != 'instance':
                raise PlatformError('application_binding_unsupported', '能力尚未声明稳定实例应用绑定：' + name)
            key = list(capability(status['installation'], kind, name, metadata))
            if binding and (status.get('installationId', status['installation']) != binding['installationId']
                    or stable != binding['instanceId'] or key != list(binding['semantic'])):
                raise PlatformError('application_binding_unavailable', name)
            if (stable, kind, name) in seen:
                return
            seen.add((stable, kind, name))
            if status['state'] != 'running' or not metadata.get('available', True):
                raise PlatformError('application_binding_unavailable', name)
            rows.append(dict(target=stable, instanceId=stable, runId=status.get('runId', status['instance']), title=status['manifest']['name'], name=name,
                             access=metadata.get('access', 'read'), kind=kind, key=key,
                             authorized=tuple(key) in scope))
            for dependency in metadata.get('bindings', {}).values():
                if not dependency.get('optional'):
                    endpoint = dependency.get('endpoint')
                    if endpoint is None:
                        raise PlatformError('application_binding_unavailable', name)
                    include(endpoint['target'], endpoint['name'], endpoint['kind'])
        for step in app.flows[flow]:
            binding = app.bindings[step['alias']]
            include(binding['target'], binding['operation'], binding=binding)
        return dict(type='application', requester=app.id, requesterInstallation=app.id,
                    requesterInstance=client.instance, subject=app.title + ' · ' + app.id,
                    target=app.id, action=flow, permissions=rows, definition=app.as_dict(), params={})

    def request_application(self, definition, flow, on_finished=None, validate=None):
        token = uuid.uuid4().hex
        instance = self.runtime.application_client(definition['applicationId']).instance
        self._approvals[token] = on_finished
        self._application_checks[token] = validate
        def prepare():
            try:
                if token not in self._approvals:
                    return None
                plan = self._make_application_plan(definition, flow)
                if plan['requesterInstance'] != instance:
                    raise PlatformError('stale_application', '应用身份已变化')
                plan['approvalToken'] = token
                return {'_view_plan': plan}
            except Exception:
                self.approvalFinished.emit(token, 'failed')
                raise
        self.submit(prepare, user_input=True)
        return token

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
        self._application_checks.pop(token, None)
        if callback: callback(status)

    def cancel_approval(self, token):
        if self._pending_plan and self._pending_plan.get('approvalToken') == token:
            self.cancelView()
        else:
            self._finish_approval(token, 'cancelled')

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
                if plan.get('type') == 'application':
                    validate = self._application_checks.get(token)
                    if validate is not None and not validate():
                        raise PlatformError('stale_application', '应用定义已变化，请重新执行')
                    current = self._make_application_plan(plan['definition'], plan['action'])
                elif plan.get('type') == 'mount':
                    current = self._make_mount_plan(plan['requester'], plan['provider'], plan['viewId'])
                else:
                    current = self._make_plan(plan['requester'], plan['target'], plan['action'])
                if (current['requesterInstallation'] != plan['requesterInstallation']
                    or current['requesterInstance'] != plan['requesterInstance']
                    or [(row['key'], row.get('runId')) for row in current['permissions']] != [(row['key'], row.get('runId')) for row in plan['permissions']]):
                    raise ValueError('能力或发起实例已变化，请重新选择')
                client = (self.runtime.application_client(plan['requester']) if plan.get('type') == 'application'
                          else self.runtime.client(plan['requester']))
                if client.instance != plan['requesterInstance']:
                    raise ValueError('发起组件已重新启动，请重新选择')
                for row in current['permissions']:
                    if not row['authorized']:
                        self.runtime.grant(plan['requester'], row['target'], row['name'], kind=row['kind'],
                                           expected_key=row['key'])
                if token and token not in self._approvals:
                    return None
                if plan.get('type') == 'application':
                    outcome = 'confirmed'
                    if plan['requiresConfirmation']:
                        return {'_application_permission_result': {'requester': plan['requester'], 'status': 'confirmed',
                                                                   'message': '授权已确认，可以继续使用应用。'}}
                    return None
                context = self.runtime.user_context(plan['requester'])
                if current.get('usesRequirements'):
                    approved = {tuple(row['key']) for row in current['permissions']}
                    context = self.runtime.derive_context(context, scope=context.scope & approved)
                result = client.call(plan['target'], plan['action'], current['params'], context=context)
                outcome = 'confirmed'
                return result
            except Exception as error:
                if plan.get('type') == 'application' and plan['requiresConfirmation']:
                    return {'_application_permission_result': {'requester': plan['requester'], 'status': 'failed',
                                                               'message': str(error)}}
                raise
            finally:
                if token: self.approvalFinished.emit(token, outcome)
        self._pending_plan = None
        self.submit(execute, user_input=True)



class Manager(Presentation):
    """Trusted extension controls presented inside the Canvas shell."""
    title = 'Polaris · 扩展管理'

    def __init__(self, runtime=None):
        super().__init__()
        self._cleanup_host = None
        self.dependencies = []
        self.views = []
        self.runtime = runtime
        self._gui = GuiDispatcher()
        self.bridge = ManagerBridge(runtime) if runtime is not None else None

    def _canvas(self):
        if self.runtime.status('canvas')['state'] != 'running':
            self.runtime.start_component('canvas')
        return self.runtime.component_instance('canvas')

    def _canvas_running(self):
        try:
            return self.runtime.status('canvas')['state'] == 'running'
        except PlatformError as error:
            if error.code == 'not_installed':
                return False
            raise

    def start(self, port):
        if self.runtime is not None:
            self.runtime.management_component_id = port.id
        super().start(port)
        if self.bridge is None and self.runtime is not None:
            self.bridge = self._gui.run(lambda: ManagerBridge(self.runtime))
        if self.bridge:
            self._gui.run(self.bridge.configure_defaults)
            self._gui.run(self.bridge.timer.start)
            self.bridge.refresh()
        if self._canvas_running():
            self._gui.run(lambda: self._canvas().actions.managementChanged.emit())

    def local_management_control(self):
        return self if self.running else None

    def request_mount(self, requester, target, view_id, on_finished=None):
        if not self.running or self.bridge is None:
            raise PlatformError('management_unavailable', '扩展管理未运行')
        self._gui.run(lambda: self._canvas().ensure_management_presentation())
        return self._gui.run(lambda: self.bridge.request_mount(requester, target, view_id, on_finished))

    def request_application(self, definition, flow, on_finished=None, validate=None):
        if not self.running or self.bridge is None:
            raise PlatformError('management_unavailable', '扩展管理未运行')
        self._gui.run(lambda: self._canvas().ensure_management_presentation())
        return self._gui.run(lambda: self.bridge.request_application(definition, flow, on_finished, validate))

    def cancel_approval(self, token):
        if self.bridge is not None:
            return self._gui.run(lambda: self.bridge.cancel_approval(token))

    def application_path(self, source_id, package_id, revision):
        return self.bridge._source_control().application_path(source_id, package_id, revision)

    def cancel_pending_ui(self):
        if self.bridge is not None:
            self._gui.run(self.bridge.cancel_all)

    def report_notice(self, message):
        def update():
            if self.bridge is not None:
                self.bridge._notice = str(message)
                self.bridge._notice_error = True
                self.bridge.changed.emit()
        self._gui.run(update)

    def refresh(self):
        if self.bridge is not None:
            self._gui.run(self.bridge.refresh)

    def status(self, context=None):
        def state():
            if not self._canvas_running():
                return {'available': False, 'visible': False}
            canvas = self._canvas()
            window = canvas.actions._window
            root = window.rootObject() if window is not None else None
            return {'available': root is not None,
                    'visible': bool(window and window.isVisible() and root.property('settingsOpen')
                                    and root.property('settingsSection') == 'extensions')}
        return dict(self._gui.run(state), running=self.running, embedded=True)

    def show(self, context=None):
        if not self.running:
            raise PlatformError('component_unavailable', '扩展管理未运行')
        bridge = self.bridge
        def display():
            if not self.running or self.bridge is not bridge:
                return
            try:
                self._canvas().open_extension_management()
            except Exception as error:
                import sys
                print('扩展管理无法显示：' + str(error), file=sys.stderr)
                self.report_notice(str(error))
        # A new GUI event leaves any public operation handling stack before the
        # shell obtains a genuine user context for local management presentation.
        self._gui.run(lambda: QTimer.singleShot(0, display))
        return dict(self.status(), pending=True)

    def hide(self, context=None):
        if not self._canvas_running():
            return self.status()
        def hide_page():
            canvas = self._canvas()
            window = canvas.actions._window
            if window is not None:
                from PySide6.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(window.rootObject(), 'showWorkspace', Qt.DirectConnection)
        self._gui.run(hide_page)
        return self.status()

    def stop(self):
        bridge = self.bridge
        if bridge:
            bridge._closed = True
            if bridge.defaults:
                bridge.defaults.cancelled.set()
            self._gui.run(bridge.cancel_all)
            self._gui.run(bridge.timer.stop)
            if bridge._worker and bridge._worker.is_alive() and bridge._worker is not threading.current_thread():
                bridge._worker.join(2)
        self.bridge = None
        def dispose():
            import shiboken6
            if self._canvas_running():
                self._canvas().actions.managementChanged.emit()
            if bridge:
                shiboken6.delete(bridge)
        self._gui.run(dispose)
        super().stop()


def create_manager(runtime=None):
    return Manager(runtime)
