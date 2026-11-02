"""Canvas-owned layout, transient sessions, and native component view mounting."""
from __future__ import annotations

import json
import threading
from pathlib import Path
import uuid

from PySide6.QtCore import QObject, Signal, Slot, QTimer, Property, QEvent, Qt, QPoint, QRect, QSize
from PySide6.QtGui import QGuiApplication, QCursor
from PySide6.QtQuick import QQuickItem

from polaris_platform.protocol import PlatformError
from polaris_platform.desktop.presentation import Presentation
from .storage import CanvasStorage, layout as validate_layout
from polaris_platform.desktop.qt_ports import GuiDispatcher


class CanvasActions(QObject):
    """Local QML bridge. It carries one existing session, never management authority."""
    added = Signal('QVariantMap')
    removed = Signal(str)
    reset = Signal()
    viewsChanged = Signal()
    themeChanged = Signal()
    failed = Signal(str, str)
    arranged = Signal(str, 'QVariantMap')

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self._window = None
        self._native_drag = False
        self._gesture = None
        self._pending_restore = None
        self.moveToThread(QGuiApplication.instance().thread())

    @Slot(QObject)
    def bindWindow(self, window):
        if self._window is window:
            return
        if self._window is not None:
            try:
                self._window.removeEventFilter(self)
            except RuntimeError:
                pass
        self._gesture = None
        self._window = window
        self._native_drag = False
        self.canvas.hold('native-frame', False)
        if window is not None:
            window.installEventFilter(self)
            window.destroyed.connect(self._window_destroyed)

    def _window_destroyed(self, window):
        if self._window is None or self._window == window:
            self._window = None
            self._gesture = None
            self._native_drag = False
            self.canvas.hold('native-frame', False)

    @Slot(int, float, float)
    def beginWindowGesture(self, edges, global_x, global_y):
        window = self._window
        if window is None:
            return
        allowed = int(Qt.LeftEdge.value | Qt.RightEdge.value | Qt.TopEdge.value | Qt.BottomEdge.value)
        horizontal = Qt.LeftEdge.value | Qt.RightEdge.value
        vertical = Qt.TopEdge.value | Qt.BottomEdge.value
        if edges & ~allowed or edges & horizontal == horizontal or edges & vertical == vertical:
            return
        self.canvas.pointer_entered()
        self._native_drag = True
        self.canvas.hold('native-frame', True)
        window.setMinimumSize(QSize(max(360, window.minimumWidth()), max(240, window.minimumHeight())))
        gesture = (edges, QPoint(round(global_x), round(global_y)), QRect(window.geometry()), True)
        self._gesture = gesture
        try:
            native = window.startSystemResize(Qt.Edges(edges)) if edges else window.startSystemMove()
        except (RuntimeError, TypeError):
            native = False
        if self._gesture is gesture:
            self._gesture = (*gesture[:3], bool(native))

    @Slot(float, float)
    def updateWindowGesture(self, global_x, global_y):
        if self._gesture is None or self._window is None:
            return
        edges, origin, initial, native = self._gesture
        if native:
            return
        delta = QPoint(round(global_x), round(global_y)) - origin
        rect = QRect(initial)
        if not edges:
            rect.translate(delta)
        else:
            minimum_width = max(360, self._window.minimumWidth())
            minimum_height = max(240, self._window.minimumHeight())
            if edges & Qt.LeftEdge.value:
                rect.setLeft(min(initial.left() + delta.x(), initial.right() - minimum_width + 1))
            if edges & Qt.RightEdge.value:
                rect.setRight(max(initial.right() + delta.x(), initial.left() + minimum_width - 1))
            if edges & Qt.TopEdge.value:
                rect.setTop(min(initial.top() + delta.y(), initial.bottom() - minimum_height + 1))
            if edges & Qt.BottomEdge.value:
                rect.setBottom(max(initial.bottom() + delta.y(), initial.top() + minimum_height - 1))
        self._window.setGeometry(rect)

    @Slot()
    def endWindowGesture(self):
        self._release_native_drag()

    @Slot()
    def cancelWindowGesture(self):
        # System move/resize may take the local mouse grab while the button is down.
        if self._gesture is not None and self._gesture[3]:
            return
        self._release_native_drag()

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() in (QEvent.MouseButtonPress, QEvent.NonClientAreaMouseButtonPress):
                self.canvas.pointer_entered()
                self._native_drag = True
                self.canvas.hold('native-frame', True)
            elif event.type() in (QEvent.MouseButtonRelease, QEvent.NonClientAreaMouseButtonRelease) and not event.buttons():
                self._release_native_drag()
            elif event.type() in (QEvent.Resize, QEvent.Move):
                if event.type() == QEvent.Resize:
                    self.canvas.save_window_size(watched.width(), watched.height())
                # Compositors may consume the frame press during a native resize.
                # Only geometry events on this canvas can establish that hold.
                if QGuiApplication.mouseButtons():
                    self.canvas.pointer_entered()
                    self._native_drag = True
                    self.canvas.hold('native-frame', True)
                QTimer.singleShot(0, self.syncPointer)
        return False

    def _release_native_drag(self):
        self._gesture = None
        self._native_drag = False
        self.syncPointer()
        self.canvas.hold('native-frame', False)

    @Slot()
    def syncPointer(self):
        import shiboken6
        window = self._window
        if window is None:
            return
        if not shiboken6.isValid(window):
            self.bindWindow(None)
            return
        if self._native_drag and not QGuiApplication.mouseButtons():
            self._release_native_drag()
            return
        if window.isVisible():
            inside = window.frameGeometry().contains(QCursor.pos())
            if inside and not self.canvas._inside:
                self.canvas.pointer_entered()
            elif not inside and self.canvas._inside:
                self.canvas.pointer_left()

    @Property(str, notify=themeChanged)
    def theme(self):
        return self.canvas._storage.theme

    @Slot(str)
    def setTheme(self, theme):
        if theme not in ('light', 'dark', 'warm') or theme == self.theme:
            return
        self.canvas._storage.theme = theme
        self.themeChanged.emit()
        self.canvas._save_layout()

    @Property(str, notify=viewsChanged)
    def viewsJson(self):
        return json.dumps(self.canvas.available_views, ensure_ascii=False)

    @Slot()
    def refreshViews(self):
        self.canvas.refresh_views()

    @Slot(int)
    def mountSelected(self, index):
        try:
            selection = self.canvas.available_views[index]
            self.canvas.request_mount_approval(selection)
        except Exception as error:
            self.failed.emit('', str(error))

    @Slot()
    def pointerEntered(self):
        self.canvas.pointer_entered()
        if self.canvas.user_access is not None:
            self._pending_restore = (self.canvas.user_access.context(), self.canvas._presentation_generation)
            QTimer.singleShot(0, self.restorePending)

    def restorePending(self):
        pending = self._pending_restore
        if pending is None:
            return
        context, generation = pending
        if not self.canvas.running or generation != self.canvas._presentation_generation:
            self._pending_restore = None
            return
        if self.canvas.handle is None or self.canvas.session_id is None:
            return  # show() consumes this already-captured input after presentation succeeds.
        self._pending_restore = None
        self.canvas.restore_layout(context)

    @Slot()
    def pointerLeft(self):
        if self._window is None:
            self.canvas.pointer_left()
        else:
            self.syncPointer()

    @Slot(str, bool)
    def hold(self, reason, active):
        self.canvas.hold(reason, active)

    @Slot()
    def dismiss(self):
        self.canvas.dismiss_async('closed')

    @Slot(str, QObject)
    def attach(self, mount_id, parent):
        self.canvas.attach_async(mount_id, parent)

    @Slot(str)
    def unmount(self, mount_id):
        try:
            context = self.canvas.user_access.context()
            self.canvas.work(lambda: self.canvas.unmount({'mountId': mount_id}, context))
        except PlatformError as error:
            self.failed.emit('', error.message)

    @Slot(str, float, float, float, float, bool)
    def layout(self, mount_id, x, y, width, height, collapsed):
        record = self.canvas.mounts.get(mount_id)
        if record is not None:
            self.canvas.set_layout(dict(mountId=mount_id, x=x, y=y, width=width, height=height, collapsed=collapsed), None)


class Canvas(Presentation):
    resource_dir = Path(__file__).parent
    source, title, size = 'Canvas.qml', 'Polaris · 画布', (880, 620)

    def __init__(self, runtime=None, window_id='window', cleanup_port=None, collapse_delay=700, data_dir=None):
        super().__init__(runtime, window_id, cleanup_port)
        self.window_options.update(frameless=True, transparent=True)
        self._data_dir = data_dir
        self._storage = CanvasStorage(data_dir)
        self.size = self._storage.size
        self._restoring = False
        self.dispatcher = GuiDispatcher()
        self.actions = CanvasActions(self)
        self.qt_context = {'canvasActions': self.actions}
        from polaris_platform.desktop.user_access import DesktopUserAccess
        self.user_access = DesktopUserAccess(runtime) if runtime is not None else None
        self.available_views = []
        self.cards = []
        self.mounts = {}
        self.session_id = None
        self.session_context = None
        self._inside = self._entered = False
        self._holds = set()
        self._workers = set()
        self._lock = threading.RLock()
        self._pointer_revision = 0
        self._generation = 0
        self._approvals = {}
        self._collapse_delay = max(0, int(collapse_delay))
        self._save_timer = self.dispatcher.run(self._make_save_timer)
        self._timer = self.dispatcher.run(self._make_timer)
        self._monitor = self.dispatcher.run(self._make_monitor)
        self.event('dismissed', provides='polaris.canvas.dismissed@1')
        self.operation('status', provides='polaris.canvas.status@1')(lambda p, c: self.status(c))
        self.operation('show', 'write', provides='polaris.canvas.show@1')(lambda p, c: self.show(c, p))
        self.operation('hide', 'write')(lambda p, c: self.hide(c, p))
        self.operation('set_cards', 'write')(self.set_cards)
        self.operation('mount', 'write')(self.mount)
        self.operation('unmount', 'write')(self.unmount)
        self.operation('layout', 'write')(self.set_layout)
        self.dependencies[0]['operations'].extend(['mount', 'set_cards'])

    def _make_save_timer(self):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(250)
        timer.timeout.connect(self._save_layout)
        return timer

    def _make_timer(self):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.dismiss_async('pointer_left'))
        return timer

    def _make_monitor(self):
        timer = QTimer()
        timer.setInterval(400)
        timer.timeout.connect(self._check_mounts)
        return timer

    def start(self, port):
        super().start(port)
        with self._lock:
            self._generation += 1
        if self.user_access is not None:
            self.user_access.bind(port.id)
            self._load_storage_directory()
        self.dispatcher.run(self._monitor.start)

    def _load_storage_directory(self):
        with self._lock:
            if self._data_dir is None and self._storage.path is None and self.user_access is not None:
                directory = self.user_access.data_directory()
                if directory is not None:
                    storage = CanvasStorage(directory)
                    storage.entries.update(self._storage.entries)
                    self._storage = storage
                    self.size = storage.size
                    self.actions.themeChanged.emit()

    def stop(self):
        with self._lock:
            self.running = False
            self._generation += 1
            self._approvals.clear()
            self.actions._pending_restore = None
            records = list(self.mounts.values())
            self.mounts.clear()
            for record in records:
                record["cancelled"] = True
        self.dispatcher.run(self._flush_layout)
        self.dispatcher.run(self._timer.stop)
        self.dispatcher.run(self._monitor.stop)
        # Disposal of the canvas tree releases presentation children, never provider data.
        for record in records:
            self._release(record)
        if self.session_id is not None:
            self._finish_session('stopped', publish=True)
        super().stop()

    def status(self, context=None):
        result = super().status(context)
        with self._lock:
            mounts = [self._public(r) for r in self.mounts.values()]
        result.update(sessionId=self.session_id, mounts=mounts)
        return result

    def show(self, context=None, params=None):
        self._load_storage_directory()
        params = params or {}
        anchor = params.get('anchor')
        if anchor is not None:
            if not isinstance(anchor, dict):
                raise PlatformError('invalid_params', 'anchor must be an object')
            self.window_options.update({key: int(anchor[key]) for key in ('x', 'y') if key in anchor})
        # Only announce a session after the actual window presentation succeeds.
        previous_handle = self.handle
        previous_hover = (self._entered, self._inside, set(self._holds))
        self._inside = bool(self._inside and self._view_state.get('visible'))
        self._entered = self._inside
        self._holds.clear()
        self.dispatcher.run(self._timer.stop)
        try:
            result = super().show(context, params)
        except Exception:
            self._entered, self._inside, self._holds = previous_hover
            raise
        if previous_handle != self.handle:
            with self._lock:
                self._generation += 1
                previous_mounts = list(self.mounts.values())
                self.mounts.clear()
                for record in previous_mounts:
                    record['cancelled'] = True
            for record in previous_mounts:
                self._release(record, context=context)
        new_session = str(params.get('sessionId') or uuid.uuid4().hex)
        if self.session_id is not None and self.session_id != new_session:
            self._finish_session('replaced')
        self.session_id = new_session
        self.session_context = context
        try:
            pointer = self._window('status', {'handle': self.handle}, context)
        except PlatformError:
            pointer = {}
        if pointer.get('pointerInside'):
            self.dispatcher.run(self.pointer_entered)
        self.dispatcher.run(self._schedule_collapse)
        self.dispatcher.run(lambda: QTimer.singleShot(0, self.actions.restorePending))
        return dict(result, sessionId=self.session_id)

    def hide(self, context=None, params=None):
        self.dispatcher.run(self._flush_layout)
        params = params or {}
        if params.get('sessionId') not in (None, self.session_id):
            return dict(self.status(), dismissed=False)
        result = super().hide(context)
        session_id = self.session_id
        self._finish_session(str(params.get('reason', 'closed')), context=context)
        return dict(result, sessionId=session_id, dismissed=session_id is not None)

    def _finish_session(self, reason, context=None, publish=True):
        with self._lock:
            session_id, session_context = self.session_id, self.session_context or context
            self.session_id = self.session_context = None
        self.dispatcher.run(self._timer.stop)
        if publish and session_id is not None and self.port is not None and session_context is not None:
            port = self.port
            def notify():
                try:
                    port.publish('dismissed', {'sessionId': session_id, 'reason': reason}, context=session_context)
                except PlatformError:
                    pass  # The lifecycle port may already be revoked while stopping.
            # A session event retains the original session context, even when a new user closes it.
            self.work(notify)

    def pointer_entered(self):
        self._pointer_revision += 1
        self._inside = self._entered = True
        self._timer.stop()

    def pointer_left(self):
        self._pointer_revision += 1
        self._inside = False
        self._schedule_collapse()

    def hold(self, reason, active):
        if (reason in self._holds) == bool(active):
            return
        self._pointer_revision += 1
        if active:
            self._holds.add(reason)
            self._timer.stop()
        else:
            self._holds.discard(reason)
            self._schedule_collapse()

    def _schedule_collapse(self):
        if self.session_id and self._entered and not self._inside and not self._holds:
            self._timer.start(self._collapse_delay)

    def dismiss_async(self, reason):
        if self.session_id is None:
            return
        session_id, context = self.session_id, self.session_context
        revision = self._pointer_revision
        def dismiss():
            def hide_current():
                if self.session_id != session_id:
                    return
                if reason == 'pointer_left':
                    self.actions.syncPointer()
                    if (revision != self._pointer_revision or not self._entered
                            or self._inside or self._holds):
                        return
                self.hide(context, {'sessionId': session_id, 'reason': reason})
            try:
                self.dispatcher.run(hide_current)
            except PlatformError as error:
                unavailable = False
                try:
                    state = self._window('status', {'handle': self.handle}, context)
                    self._view_state = {'available': bool(state.get('available')), 'visible': bool(state.get('visible'))}
                    unavailable = not state.get('available')
                except PlatformError:
                    if self.user_access is not None:
                        unavailable = self.user_access.status(self.window_id)['state'] in ('stopped', 'failed')
                if unavailable:
                    self._view_state = {'available': False, 'visible': False, 'reason': error.message}
                    self._finish_session('unavailable', context=context)
                else:
                    self.actions.failed.emit('', error.message)
        self.work(dismiss)

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
        self.cards = [{'title': str(c.get('title', '')), 'text': str(c.get('text', ''))} for c in cards]
        self.properties['cardsJson'] = json.dumps(self.cards, ensure_ascii=False)
        if self.handle:
            self._window('update', {'handle': self.handle, 'properties': self.properties}, context)
        return {'count': len(self.cards)}

    def request_mount_approval(self, selection):
        reason = 'approval-' + uuid.uuid4().hex
        generation, session_id = self._generation, self.session_id
        self._approvals[reason] = (generation, session_id)
        self.hold(reason, True)
        def finished(*_):
            def release():
                expected = self._approvals.pop(reason, None)
                if expected == (self._generation, self.session_id):
                    self.hold(reason, False)
            self.dispatcher.run(release)
        try:
            self.user_access.prepare_mount(selection['target'], selection['descriptor'], on_finished=finished)
        except Exception:
            finished()
            raise

    def refresh_views(self):
        self.available_views = []
        if self.user_access is not None:
            for component in self.user_access.snapshot():
                if component['state'] != 'running':
                    continue
                for descriptor in component.get('description', {}).get('views', []):
                    if descriptor.get('adapter') == 'qt-quick-item':
                        self.available_views.append(dict(target=component['id'], componentName=component['manifest']['name'],
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
        client = self.port
        if client is None or not self.running:
            raise PlatformError('component_unavailable', 'Canvas is stopped')
        bound = client.bind(target, create)
        release_bound = client.bind(target, release)
        window_state = self._window('status', {'handle': self.handle}, context)
        if self.session_id is None or not window_state.get('visible'):
            self.show(context, {})
        layout_id = layout_id or uuid.uuid4().hex
        mount_id = uuid.uuid4().hex
        position = len(self.mounts) + len(self.cards)
        record = dict(mountId=mount_id, layoutId=layout_id, target=target, view=view_id, title=str(descriptor.get('title', target)),
                      create=create, release=release, bound=bound, release_bound=release_bound, context=context, handle=None,
                      state='pending', error='', container=None, item=None, client=client, cancelled=False,
                      layout=dict(x=24 + (position % 2) * 390, y=10 + (position // 2) * 240,
                                  width=370, height=220, collapsed=False))
        with self._lock:
            if not self.running or self.port is not client:
                raise PlatformError('component_unavailable', 'Canvas stopped before mounting')
            saved = self._storage.entries.get(layout_id)
            if saved is not None:
                record['layout'] = dict(saved['layout'])
            else:
                self._storage.entries[layout_id] = dict(id=layout_id, target=target, view=view_id, layout=dict(record['layout']))
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
                    and self.port is record['client'] and self._generation == record['generation']
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

    def save_window_size(self, width, height):
        with self._lock:
            if width > 0 and height > 0 and (int(width), int(height)) != self._storage.size:
                self.size = self._storage.size = (int(width), int(height))
                self._save_timer.start()

    def _flush_layout(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_layout()

    def restore_layout(self, context):
        # Rebuild using current public declarations and the caller's existing authority.
        # A local pointer entry supplies a fresh, canvas-owned user input context.
        with self._lock:
            if self._restoring or not self.running or not self.handle:
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
                selection = next((v for v in self.available_views if v['target'] == saved['target'] and v['descriptor']['id'] == saved['view']), None)
                if selection is None:
                    continue
                try:
                    self._mount(dict(target=saved['target'], view=saved['view'], descriptor=selection['descriptor']), context, layout_id=identity)
                except PlatformError:
                    pass  # Keep intent intact for a later authorized local input.
        finally:
            with self._lock:
                self._restoring = False

    def _check_mounts(self):
        if self.port is None:
            return
        if self.session_id is not None:
            try:
                state = self._window('status', {'handle': self.handle}, self.session_context)
                if not state.get('available') or not state.get('visible'):
                    self.dismiss_async('closed')
                elif self.actions._window is not None:
                    self.actions.syncPointer()
                elif state.get('pointerInside') is True and not self._inside:
                    self.pointer_entered()
                elif state.get('pointerInside') is False and self._inside:
                    self.pointer_left()
            except PlatformError as error:
                if error.code in ('unavailable', 'window_unavailable', 'dependency_unavailable', 'stale_instance'):
                    self.dismiss_async('unavailable')
                else:
                    self.actions.failed.emit('', error.message)
        for mount_id, record in list(self.mounts.items()):
            try:
                import shiboken6
                live_item = record['item'] is None or shiboken6.isValid(record['item'])
                live_parent = record['container'] is None or shiboken6.isValid(record['container'])
                if live_item and live_parent and self.port.bind(record['target'], record['create']) == record['bound']:
                    continue
            except PlatformError:
                pass
            with self._lock:
                self.mounts.pop(mount_id, None)
                record['cancelled'] = True
            self.work(lambda record=record: self._release(record))


def create_canvas(runtime=None, window_id='window', cleanup_port=None, collapse_delay=700, data_dir=None):
    return Canvas(runtime, window_id, cleanup_port, collapse_delay, data_dir)
