"""Built-in workbench: native presentations, cards, and their saved layout."""
from __future__ import annotations
import json
import math
import threading
import uuid
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlEngine, QQmlComponent, QQmlContext
from polaris_platform.application import Application
from polaris_platform.protocol import PlatformError
from polaris_platform.desktop.qt_ports import GuiDispatcher
from .storage import layout as validate_layout

WORKBENCH_ID = 'f3bcb2d1737d4f4e9c57c5ea63f68209'

class WorkbenchActions(QObject):
    added = Signal('QVariantMap')
    removed = Signal(str)
    reset = Signal()
    viewsChanged = Signal()
    themeChanged = Signal()
    cardsChanged = Signal()
    failed = Signal(str, str)
    arranged = Signal(str, 'QVariantMap')
    pickerRequested = Signal()
    contentChanged = Signal()
    runningChanged = Signal()
    def __init__(self, workbench):
        super().__init__()
        self.workbench = workbench
        self.moveToThread(QGuiApplication.instance().thread())
        self.added.connect(self.contentChanged)
        self.removed.connect(self.contentChanged)
        self.cardsChanged.connect(self.contentChanged)
        self.reset.connect(self.contentChanged)
    @Property(bool, notify=runningChanged)
    def running(self):
        return self.workbench.running
    @Property(bool, notify=contentChanged)
    def empty(self):
        return not self.workbench.mounts and not self.workbench.cards
    @Property(str, notify=themeChanged)
    def theme(self):
        return self.workbench.display.theme
    @Property(str, notify=cardsChanged)
    def cardsJson(self):
        return json.dumps(self.workbench.cards, ensure_ascii=False)
    @Slot()
    def chooseView(self):
        self.workbench.refresh_views()
        self.pickerRequested.emit()
    @Slot(str, bool)
    def hold(self, reason, active):
        self.workbench.display.hold(reason, active)

    @Property(str, notify=viewsChanged)
    def viewsJson(self):
        return json.dumps(self.workbench.available_views, ensure_ascii=False)


    @Slot()
    def refreshViews(self):
        self.workbench.refresh_views()


    @Slot(int)
    def mountSelected(self, index):
        try:
            selection = self.workbench.available_views[index]
            self.workbench.request_mount_approval(selection)
        except Exception as error:
            self.failed.emit('', str(error))


    @Slot(str, QObject)
    def attach(self, mount_id, parent):
        self.workbench.attach_async(mount_id, parent)


    @Slot(str)
    def unmount(self, mount_id):
        try:
            context = self.workbench.display.context()
            self.workbench.work(lambda: self.workbench.unmount({'mountId': mount_id}, context))
        except PlatformError as error:
            self.failed.emit('', error.message)


    @Slot(float)
    def arrange(self, available_width):
        with self.workbench._lock:
            columns = max(1, int((max(0, available_width - 32) + 16) // 346))
            text_rows = (len(self.workbench.cards) + columns - 1) // columns
            x, y, row_height = 16, 8 + text_rows * 176, 0
            limit = max(240, available_width - 16)
            for record in list(self.workbench.mounts.values()):
                width, height = record['preferredSize']
                if x > 16 and x + width > limit:
                    x, y, row_height = 16, y + row_height + 16, 0
                self.workbench.set_layout(dict(mountId=record['mountId'], x=x, y=y,
                                            width=width, height=height,
                                            collapsed=record['layout']['collapsed']), None)
                x += width + 16
                row_height = max(row_height, 44 if record['layout']['collapsed'] else height)


    @Slot(str, float, float, float, float, bool)
    def layout(self, mount_id, x, y, width, height, collapsed):
        record = self.workbench.mounts.get(mount_id)
        if record is not None:
            self.workbench.set_layout(dict(mountId=mount_id, x=x, y=y, width=width, height=height, collapsed=collapsed), None)



class Workbench(Application):
    def __init__(self, display):
        super().__init__('工作台', application_id=WORKBENCH_ID)
        self.display = display
        self.actions = WorkbenchActions(self)
        self.dispatcher = GuiDispatcher()
        self.available_views = []
        self.cards = []
        self.mounts = {}
        self._lock = display.layout_lock
        self._workers = set()
        self._approvals = {}
        self._approval_tokens = {}
        self._epoch = 0
        self._restoring = False
        self._pending_restore = None
        self.running = False
        self._view = None
        self._detached = []

    @property
    def _storage(self): return self.display.storage
    @property
    def _generation(self): return (self.display.generation, self._epoch)
    @property
    def size(self): return self.display.size

    def start(self, port):
        super().start(port)
        self._epoch += 1
        self.running = True
        self.actions.runningChanged.emit()

    def stop(self):
        self.running = False
        self.actions.runningChanged.emit()
        self._pending_restore = None
        self._epoch += 1
        def cancel():
            for reason, token in list(self._approval_tokens.items()):
                self.display.cancel_approval(token)
                self.display.hold(reason, False)
            self._approval_tokens.clear()
            self._approvals.clear()
        self.dispatcher.run(cancel)
        if self._view is not None and self._view.root is not None:
            self.dispatcher.run(lambda: self._view.set_active(False))
        self.reset_presentations()
        super().stop()

    def reset_presentations(self, context=None, remember=False):
        with self._lock:
            records = list(self.mounts.values())
            self._detached = [(dict(target=r['target'], view=r['view']), r['context'], r['layoutId']) for r in records] if remember else []
            self.mounts.clear()
            for record in records:
                record['cancelled'] = True
        for record in records:
            self._release(record, context)
        self.actions.reset.emit()

    def capture_restore(self):
        self._pending_restore = (self.display.context(), self.display.presentation_generation)
        QTimer.singleShot(0, self.restore_pending)

    def restore_pending(self):
        if self._pending_restore is None:
            return
        context, generation = self._pending_restore
        if not self.running or generation != self.display.presentation_generation:
            self._pending_restore = None
            return
        if self.display.handle is None or self.display.session_id is None:
            return
        self._pending_restore = None
        self.restore_layout(context)

    def create_view(self, parent, header_parent):
        self._view = WorkbenchView(self, parent, header_parent)
        return self._view

    def work(self, callback):
        def execute():
            try:
                callback()
            except Exception as error:
                self.actions.failed.emit('', str(error))
            finally:
                self._workers.discard(threading.current_thread())
        thread = threading.Thread(target=execute, daemon=True)
        self._workers.add(thread)
        thread.start()


    def set_cards(self, params, context):
        cards = params.get('cards', [])
        if not isinstance(cards, list) or any(not isinstance(c, dict) for c in cards):
            raise PlatformError('invalid_params', '卡片应为对象列表')
        with self._lock:
            self.cards = [{'title': str(c.get('title', '')), 'text': str(c.get('text', ''))} for c in cards]
        self.actions.cardsChanged.emit()
        return {'count': len(self.cards)}


    def request_mount_approval(self, selection):
        reason = 'approval-' + uuid.uuid4().hex
        generation, session_id = self._generation, self.display.session_id
        self._approvals[reason] = (generation, session_id)
        self.display.hold(reason, True)
        def finished(*_):
            def release():
                self._approval_tokens.pop(reason, None)
                expected = self._approvals.pop(reason, None)
                if expected == (self._generation, self.display.session_id):
                    self.display.hold(reason, False)
            self.dispatcher.run(release)
        try:
            token = self.display.prepare_mount(selection['target'], selection['descriptor'], on_finished=finished)
            if reason in self._approvals:
                self._approval_tokens[reason] = token
        except Exception:
            finished()
            raise


    @staticmethod
    def _instance_suffix(component):
        if component['manifest'].get('instances', {}).get('mode') != 'multiple':
            return ''
        if component.get('isDefault', True):
            return ' · 默认实例'
        return ' · 实例 ' + component.get('instanceId', component['id'])[:8]


    def refresh_views(self):
        self.available_views = []
        if self.display.has_user_access:
            for component in self.display.snapshot():
                if component['state'] != 'running':
                    continue
                for descriptor in component.get('description', {}).get('views', []):
                    if descriptor.get('adapter') == 'qt-quick-item':
                        self.available_views.append(dict(target=component.get('instanceId', component['id']), stableInstanceId=component.get('instanceId'), componentName=component['manifest']['name'] + self._instance_suffix(component),
                            title=descriptor.get('title', descriptor['id']), descriptor=descriptor))
        self.actions.viewsChanged.emit()


    def mount(self, params, context):
        return self._mount(params, context)


    def _mount(self, params, context, layout_id=None):
        target = params.get('target')
        if not isinstance(target, str):
            raise PlatformError('invalid_params', 'View target is required')
        descriptor = params.get('descriptor') or {}
        if descriptor.get('adapter', 'qt-quick-item') != 'qt-quick-item':
            raise PlatformError('unsupported_view', 'This mount requires the trusted local Qt item profile')
        view_id = str(params.get('view', descriptor.get('id', 'main')))
        create = str(descriptor.get('create', 'create_view'))
        release = str(descriptor.get('release', 'release_view'))
        client = self.display.client
        if client is None or not self.running:
            raise PlatformError('component_unavailable', 'Canvas is stopped')
        bound = client.bind(target, create)
        release_bound = client.bind(target, release)
        stable_id = getattr(bound, 'instanceId', None)
        if stable_id:
            target = stable_id
        declared = None
        current = None
        if self.display.has_user_access:
            current = self.display.status(target)
            declared = next((view for view in current.get('description', {}).get('views', []) if view.get('id') == view_id), None)
            if declared is not None:
                descriptor = {**declared, **descriptor}
                create = str(declared.get('create', 'create_view'))
                release = str(declared.get('release', 'release_view'))
                bound = client.bind(target, create)
                release_bound = client.bind(target, release)
        policy = (declared or descriptor).get('instancePolicy', 'multiple')
        if policy not in ('single', 'multiple'):
            raise PlatformError('invalid_view_policy', 'Unknown view instance policy')
        if policy == 'single':
            if not self.display.has_user_access:
                raise PlatformError('permission_required', 'Single-view reuse requires verified caller authority')
            checks = [bound, release_bound]
            for permission in (declared or descriptor).get('permissions', []):
                if permission.get('kind', 'operation') == 'operation':
                    checks.append(client.bind(permission.get('target', target), permission['name']))
            self.display.check_capabilities(context, checks)
        window_state = self.display.window('status', {'handle': self.display.handle}, context)
        if self.display.session_id is None or not window_state.get('visible'):
            self.display.show(context, {})
        restoring_layout = layout_id is not None
        layout_id = layout_id or uuid.uuid4().hex
        mount_id = uuid.uuid4().hex
        preferred = descriptor.get('preferredSize')
        preferred = preferred if isinstance(preferred, dict) else {}
        def dimension(key, fallback, minimum, maximum):
            value = preferred.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                return fallback
            return max(minimum, min(maximum, int(value)))
        card_width = dimension('width', 380, 240, 1600)
        card_height = dimension('height', 340, 130, 1200)
        with self._lock:
            # Duplicate selection and insertion share this lock, including
            # concurrent calls arriving before either provider item is attached.
            if policy == 'single':
                duplicate = next((record for record in self.mounts.values()
                                  if record['target'] == target and record['view'] == view_id
                                  and not record['cancelled']), None)
                if duplicate is not None:
                    if restoring_layout and duplicate['layoutId'] != layout_id:
                        raise PlatformError('view_layout_conflict', '单视图存在重复保存布局，请移除重复布局后重试')
                    previous = duplicate['context']
                    if (previous.origin != context.origin or previous.source != context.source
                            or previous.origin_installation != context.origin_installation
                            or not previous.scope <= context.scope):
                        raise PlatformError('view_context_conflict', '已有视图使用不同授权范围，请先关闭再重新打开')
                    if duplicate['layout']['collapsed']:
                        self.set_layout(dict(mountId=duplicate['mountId'], collapsed=False), context)
                    return dict(mountId=duplicate['mountId'], state=duplicate['state'], reused=True)
            # Find a free position using current geometries, including user-moved cards.
            existing = [dict(r['layout']) for r in self.mounts.values()]
            # Text cards use a Flow with 330×160 items and a 16 px gap.
            columns = max(1, int((max(0, self.size[0] - 128) + 16) // 346))
            existing += [dict(x=12 + (i % columns) * 346, y=8 + (i // columns) * 176,
                              width=330, height=160, collapsed=False) for i in range(len(self.cards))]
            xs = sorted({16, *(r['x'] + r['width'] + 16 for r in existing)})
            ys = sorted({8, *(r['y'] + (44 if r['collapsed'] else r['height']) + 16 for r in existing)})
            limit = max(card_width + 16, self.size[0] - 112)
            x, y = 16, max(ys)
            for candidate_y in ys:
                found = False
                for candidate_x in xs:
                    if candidate_x + card_width > limit:
                        continue
                    if all(candidate_x + card_width + 16 <= r['x'] or
                           candidate_x >= r['x'] + r['width'] + 16 or
                           candidate_y + card_height + 16 <= r['y'] or
                           candidate_y >= r['y'] + (44 if r['collapsed'] else r['height']) + 16
                           for r in existing):
                        x, y, found = candidate_x, candidate_y, True
                        break
                if found:
                    break
            record = dict(mountId=mount_id, layoutId=layout_id, target=target, stableInstanceId=stable_id, view=view_id, title=str(descriptor.get('title', target)) + (self._instance_suffix(current) if current else ''),
                          create=create, release=release, bound=bound, release_bound=release_bound, context=context, handle=None,
                          state='pending', error='', container=None, item=None, client=client, cancelled=False,
                          preferredSize=(card_width, card_height),
                          layout=dict(x=x, y=y, width=card_width, height=card_height, collapsed=False))
            if not self.running or self.display.client is not client:
                raise PlatformError('component_unavailable', 'Canvas stopped before mounting')
            saved = self._storage.entries.get(layout_id)
            if saved is not None:
                record['layout'] = dict(saved['layout'])
                if stable_id and not saved.get('stableInstanceId'):
                    saved.update(target=target, stableInstanceId=stable_id)
                    self._save_layout()
            else:
                self._storage.entries[layout_id] = dict(id=layout_id, target=target, stableInstanceId=stable_id, view=view_id, layout=dict(record['layout']))
                self._save_layout()
            record['generation'] = self._generation
            self.mounts[mount_id] = record
        def announce():
            if self._mount_current(record):
                self.actions.added.emit(self._public(record))
                return True
            return False
        if not self.dispatcher.run(announce):
            raise PlatformError('stale_instance', 'The canvas presentation changed before mounting')
        return {'mountId': mount_id, 'state': 'pending'}


    @staticmethod
    def _public(record):
        return {**{key: record[key] for key in ('mountId', 'target', 'view', 'title', 'state', 'error')},
                'layout': dict(record['layout'])}


    def _mount_current(self, record):
        with self._lock:
            return (self.running and not record['cancelled']
                    and self.display.client is record['client'] and self._generation == record['generation']
                    and self.mounts.get(record['mountId']) is record)


    def attach_async(self, mount_id, parent):
        with self._lock:
            record = self.mounts.get(mount_id)
            if record is None or record['state'] != 'pending' or not self._mount_current(record):
                return
            record['state'] = 'attaching'
            record['container'] = parent
        client, context = record['client'], record['context']
        def create_on_gui():
            import shiboken6
            # Check the native parent on its GUI thread, immediately before entering the provider.
            if not self._mount_current(record):
                return
            if not shiboken6.isValid(parent):
                with self._lock:
                    self.mounts.pop(mount_id, None)
                    record['cancelled'] = True
                self.actions.removed.emit(mount_id)
                return
            result = client.invoke(record['bound'], {'view': record['view'], 'parent': parent}, context=context)
            if not isinstance(result, dict) or not isinstance(result.get('item'), QQuickItem) or not isinstance(result.get('handle'), str):
                raise PlatformError('invalid_view', 'Provider must return a native item and an owned handle')
            item = result['item']
            if not self._mount_current(record) or not shiboken6.isValid(parent) or not shiboken6.isValid(item):
                # Dispose using the original identity/handle only; never route to a new instance.
                try:
                    client.invoke(record['release_bound'], {'handle': result['handle']}, context=context)
                except PlatformError:
                    if shiboken6.isValid(item):
                        item.setVisible(False)
                return
            record['resize_disconnect'] = self._fit_native(item, parent)
            record.update(handle=result['handle'], item=item, state='mounted')
        def attach():
            try:
                self.dispatcher.run(create_on_gui)
            except Exception as error:
                if self._mount_current(record):
                    record.update(state='unavailable', error=str(error))
                    self.actions.failed.emit(mount_id, str(error))
        self.work(attach)


    @staticmethod
    def _fit_native(item, parent):
        import shiboken6
        disconnected = False
        def fit():
            if shiboken6.isValid(item) and shiboken6.isValid(parent):
                item.setWidth(parent.width())
                item.setHeight(parent.height())
        def disconnect(*_):
            nonlocal disconnected
            if disconnected:
                return
            disconnected = True
            if shiboken6.isValid(parent):
                for signal in (parent.widthChanged, parent.heightChanged):
                    try:
                        signal.disconnect(fit)
                    except (RuntimeError, TypeError):
                        pass
        fit()
        parent.widthChanged.connect(fit)
        parent.heightChanged.connect(fit)
        item.destroyed.connect(disconnect)
        parent.destroyed.connect(disconnect)
        return disconnect


    def _release(self, record, context=None):
        if record.get("resize_disconnect"):
            self.dispatcher.run(record["resize_disconnect"])
        if record['handle']:
            try:
                record['client'].invoke(record['release_bound'], {'handle': record['handle']}, context=context or record['context'])
            except PlatformError:
                pass
        self.actions.removed.emit(record['mountId'])


    def unmount(self, params, context):
        mount_id = params.get('mountId')
        with self._lock:
            record = self.mounts.pop(mount_id, None)
            if record is not None:
                record['cancelled'] = True
                self._storage.entries.pop(record['layoutId'], None)
                self._save_layout()
        if record is not None:
            self._release(record, context=context)
        return {'released': record is not None}


    def set_layout(self, params, context):
        with self._lock:
            record = self.mounts.get(params.get('mountId'))
            if record is None:
                raise PlatformError('missing_view', 'Unknown mount')
            try:
                record['layout'] = validate_layout({**record['layout'], **{key: params[key] for key in ('x', 'y', 'width', 'height', 'collapsed') if key in params}})
            except (ValueError, KeyError, TypeError) as error:
                raise PlatformError('invalid_params', str(error)) from error
            self._storage.entries[record['layoutId']]['layout'] = dict(record['layout'])
            self._save_layout()
        self.actions.arranged.emit(record['mountId'], record['layout'])
        return self._public(record)


    def _save_layout(self):
        with self._lock:
            try:
                self._storage.save()
            except (OSError, ValueError) as error:
                self.actions.failed.emit('', str(error))


    def restore_layout(self, context):
        # Rebuild using current public declarations and the caller's existing authority.
        # A local pointer entry supplies a fresh, canvas-owned user input context.
        with self._lock:
            if self._restoring or not self.running or not self.display.handle:
                return
            self._restoring = True
        try:
            if self._storage.error is not None:
                self.actions.failed.emit('', '画布布局文件无法读取，已保留原文件：' + self._storage.error)
            self.refresh_views()
            with self._lock:
                saved_entries = list(self._storage.entries.items())
            for identity, saved in saved_entries:
                with self._lock:
                    existing = next((r for r in self.mounts.values() if r['layoutId'] == identity), None)
                    if existing is not None:
                        if existing['state'] != 'unavailable':
                            continue
                        self.mounts.pop(existing['mountId'], None)
                        existing['cancelled'] = True
                if existing is not None:
                    self._release(existing, context=context)
                saved_target = saved.get('stableInstanceId') or saved['target']
                selection = next((v for v in self.available_views if v['target'] == saved_target and v['descriptor']['id'] == saved['view']), None)
                if selection is None and not saved.get('stableInstanceId'):
                    # Legacy aliases may resolve only to the current default instance.
                    try:
                        stable = self.display.status(saved_target).get('instanceId', saved_target)
                        selection = next((v for v in self.available_views if v['target'] == stable and v['descriptor']['id'] == saved['view']), None)
                    except PlatformError:
                        pass
                if selection is None:
                    continue
                try:
                    self._mount(dict(target=selection['target'], view=saved['view'], descriptor=selection['descriptor']), context, layout_id=identity)
                except PlatformError as error:
                    if error.code == 'view_layout_conflict':
                        self.actions.failed.emit('', error.message)
                    pass  # Keep intent intact for a later authorized local input.
        finally:
            with self._lock:
                self._restoring = False


    def check_mounts(self):
        for mount_id, record in list(self.mounts.items()):
            try:
                import shiboken6
                live_item = record['item'] is None or shiboken6.isValid(record['item'])
                live_parent = record['container'] is None or shiboken6.isValid(record['container'])
                if live_item and live_parent and self.display.client.bind(record['target'], record['create']) == record['bound']:
                    continue
            except PlatformError:
                pass
            with self._lock:
                self.mounts.pop(mount_id, None)
                record['cancelled'] = True
            self.work(lambda record=record: self._release(record))




class WorkbenchView:
    """Workbench body and header share one isolated QML engine."""
    def __init__(self, workbench, parent, header_parent):
        self.workbench, self.parent, self.header_parent = workbench, parent, header_parent
        self._closed = False
        self.engine = QQmlEngine()
        from polaris_platform.ui import configure_qml_engine
        configure_qml_engine(self.engine)
        self.context = QQmlContext(self.engine.rootContext())
        self.context.setContextProperty('workbenchActions', workbench.actions)
        self.theme_component = QQmlComponent(self.engine)
        self.theme_component.setData(b'import Polaris.Ui 1.0 as Ui\nUi.Theme {}', QUrl())
        self.theme = self.theme_component.create(self.context)
        self.theme.setParent(self.engine)
        self.update_theme()
        workbench.actions.themeChanged.connect(self.update_theme)
        self.context.setContextProperty('workbenchTheme', self.theme)
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Workbench.qml'))))
        self.root = self.component.create(self.context)
        if not isinstance(self.root, QQuickItem):
            raise PlatformError('application_ui_failed', '; '.join(e.toString() for e in self.component.errors()))
        self.root.destroyed.connect(self._root_destroyed)
        self.root.setParent(parent)
        self.root.setParentItem(parent)
        self.header_component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Toolbar.qml'))))
        self.header = self.header_component.createWithInitialProperties({'body': self.root}, self.context)
        if not isinstance(self.header, QQuickItem):
            raise PlatformError('application_ui_failed', '; '.join(e.toString() for e in self.header_component.errors()))
        self.header.setParent(header_parent)
        self.header.setParentItem(header_parent)
        parent.widthChanged.connect(self.resize)
        parent.heightChanged.connect(self.resize)
        self.resize()
        for record in workbench.mounts.values():
            workbench.actions.added.emit(workbench._public(record))

    def update_theme(self):
        self.theme.setProperty('mode', self.workbench.display.theme)

    def selected_from_input(self):
        self.workbench.capture_restore()

    def _root_destroyed(self):
        self.root = None

    def resize(self):
        import shiboken6
        if self.root is not None and shiboken6.isValid(self.root) and shiboken6.isValid(self.parent):
            self.root.setWidth(self.parent.width())
            self.root.setHeight(self.parent.height())

    def set_active(self, active):
        import shiboken6
        if self.root is not None and shiboken6.isValid(self.root):
            self.root.setProperty('presentationActive', bool(active))
            self.root.setVisible(bool(active))
            self.root.setEnabled(bool(active))
            if active and self.workbench._detached:
                saved, self.workbench._detached = self.workbench._detached, []
                for params, context, layout_id in saved:
                    try:
                        self.workbench._mount(params, context, layout_id=layout_id)
                    except PlatformError as error:
                        self.workbench.actions.failed.emit('', error.message)
        if shiboken6.isValid(self.header):
            self.header.setVisible(bool(active))
            self.header.setEnabled(bool(active))

    def close(self):
        import shiboken6
        if self._closed:
            return
        self._closed = True
        if self.root is not None and shiboken6.isValid(self.root):
            self.root.setProperty('updatesEnabled', False)
        self.workbench.actions.themeChanged.disconnect(self.update_theme)
        self.workbench.reset_presentations(remember=True)
        if shiboken6.isValid(self.parent):
            self.parent.widthChanged.disconnect(self.resize)
            self.parent.heightChanged.disconnect(self.resize)
        root, self.root = self.root, None
        for item in (self.header, root):
            if item is not None and shiboken6.isValid(item):
                item.setEnabled(False)
                item.setParentItem(None)
                item.deleteLater()
        for resource in (self.theme, self.context, self.header_component, self.component, self.theme_component, self.engine):
            if shiboken6.isValid(resource):
                resource.deleteLater()
