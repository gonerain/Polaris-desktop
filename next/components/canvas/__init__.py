"""Desktop shell, window sessions, and public workbench operation routing."""
from __future__ import annotations

import json
import threading
from pathlib import Path
import uuid

from PySide6.QtCore import QObject, Signal, Slot, QTimer, Property, QEvent, Qt, QPoint, QRect, QSize, QMetaObject
from PySide6.QtGui import QGuiApplication, QCursor

from polaris_platform.protocol import PlatformError
from polaris_platform.metadata import VERSION
from polaris_platform.desktop.management_control import ManagementControlPort
from polaris_platform.desktop.presentation import Presentation
from polaris_platform.builtin_apps.workbench import Workbench, WORKBENCH_ID
from polaris_platform.builtin_apps.workbench.storage import CanvasStorage
from polaris_platform.desktop.qt_ports import GuiDispatcher



class CanvasActions(QObject):
    """Shell window, appearance, and local pointer controls."""
    themeChanged = Signal()
    managementChanged = Signal()
    failed = Signal(str, str)
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self._window = None
        self._native_drag = False
        self._gesture = None
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
            window.destroyed.connect(lambda: self._window_destroyed(window))


    def _window_destroyed(self, window):
        if self._window is window:
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


    @Property(str, constant=True)
    def applicationVersion(self):
        return VERSION


    @Slot()
    def showComponentManager(self):
        try:
            self.canvas._management_control.show()
        except PlatformError as error:
            self.failed.emit('', error.message)

    @Property(QObject, notify=managementChanged)
    def managementBridge(self):
        return self.canvas._management_control.bridge()

    @Slot(str)
    def openComponentView(self, identity):
        try:
            status = self.canvas.user_access.status(identity)
            actions = [action for view in status['description'].get('views', [])
                       for action in view.get('actions', [])]
            if actions:
                self.managementBridge.prepareView(self.canvas.port.id, identity, actions[0]['operation'])
                return
            self.canvas.workbench.refresh_views()
            index = next(index for index, row in enumerate(self.canvas.workbench.available_views)
                         if row['target'] in (identity, status['instanceId']))
            self.canvas.workbench.actions.mountSelected(index)
        except Exception as error:
            self.failed.emit('', str(error))


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


    @Slot()
    def pointerEntered(self):
        self.canvas.pointer_entered()
        if self.canvas.user_access is not None:
            self.canvas.workbench.capture_restore()

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



class NativeDisplayClient:
    """Only native-display collaboration calls retain the Canvas identity."""
    def __init__(self, client): self._client = client
    def bind(self, target, operation): return self._client.bind(target, operation)
    def invoke(self, bound, params, context): return self._client.invoke(bound, params, context=context)


class WorkbenchDisplayPort:
    """Trusted display boundary; never exported into ordinary application QML."""
    def __init__(self, canvas):
        self._canvas = canvas
        self.client = None
    @property
    def layout_lock(self): return self._canvas._lock
    @property
    def storage(self): return self._canvas._storage
    @property
    def generation(self): return self._canvas._generation
    @property
    def presentation_generation(self): return self._canvas._presentation_generation
    @property
    def handle(self): return self._canvas.handle
    @property
    def session_id(self): return self._canvas.session_id
    @property
    def size(self): return self._canvas.size
    @property
    def theme(self): return self._canvas._storage.theme
    @property
    def has_user_access(self): return self._canvas.user_access is not None
    def window(self, operation, params, context): return self._canvas._window(operation, params, context)
    def show(self, context, params): return self._canvas.show(context, params)
    def hold(self, reason, active): self._canvas.hold(reason, active)
    def context(self): return self._canvas.user_access.context()
    def snapshot(self): return self._canvas.user_access.snapshot()
    def status(self, target): return self._canvas.user_access.status(target)
    def check_capabilities(self, context, checks): return self._canvas.user_access.check_capabilities(context, checks)
    def cancel_approval(self, token): return self._canvas._management_control.cancel_approval(token)
    def prepare_mount(self, target, descriptor, on_finished): return self._canvas.user_access.prepare_mount(target, descriptor, on_finished)


class Canvas(Presentation):
    resource_dir = Path(__file__).parent
    source, title, size = 'Canvas.qml', 'Polaris · 画布', (1120, 760)

    def __init__(self, runtime=None, window_id='window', cleanup_port=None, collapse_delay=700, data_dir=None):
        super().__init__(runtime, window_id, cleanup_port)
        self.window_options.update(frameless=True, transparent=True)
        self._data_dir = data_dir
        self._storage = CanvasStorage(data_dir)
        self.size = self._storage.size
        self.dispatcher = GuiDispatcher()
        self._management_control = ManagementControlPort(runtime)
        self._management_context = None
        self.actions = CanvasActions(self)
        self.application_host = None
        if runtime is not None:
            from polaris_platform.desktop.application_host import ApplicationHost
            self.application_host = ApplicationHost(runtime, self.hold)
        from polaris_platform.desktop.user_access import DesktopUserAccess
        self.user_access = DesktopUserAccess(runtime) if runtime is not None else None
        self.session_id = None
        self.session_context = None
        self._inside = self._entered = False
        self._holds = set()
        self._workers = set()
        self._lock = threading.RLock()
        self._pointer_revision = 0
        self._generation = 0
        self._collapse_delay = max(0, int(collapse_delay))
        self.display_port = WorkbenchDisplayPort(self)
        self.workbench = Workbench(self.display_port)
        self.workbench.actions.failed.connect(self.actions.failed)
        self.actions.themeChanged.connect(self.workbench.actions.themeChanged)
        if self.application_host is not None:
            self.workbench.actions.runningChanged.connect(self.application_host._update_views)
        self._builtin_registered = False
        self.qt_context = {'canvasActions': self.actions, 'applicationHost': self.application_host}
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
        self.display_port.client = NativeDisplayClient(port)
        if self.application_host is not None:
            if not self._builtin_registered:
                self.dispatcher.run(lambda: self.application_host.register_builtin(self.workbench, self.workbench.create_view, component_type='org.polaris.workbench', version='1'))
                self._builtin_registered = True
            else:
                self.application_host.runtime.start_application(WORKBENCH_ID)
            directory = self._storage.path.parent if self._storage.path else None
            self.dispatcher.run(lambda: self.application_host.configure(directory))
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
        self._management_control.cancel_pending_ui()
        with self._lock:
            self.running = False
            self._generation += 1
        if self.application_host is not None:
            self.dispatcher.run(self.application_host.close)
        if self.application_host is not None:
            self.application_host.runtime.stop_application(WORKBENCH_ID)
        self.dispatcher.run(self._flush_layout)
        self.dispatcher.run(self._timer.stop)
        self.dispatcher.run(self._monitor.stop)
        if self.session_id is not None:
            self._finish_session('stopped', publish=True)
        super().stop()


    def status(self, context=None):
        result = super().status(context)
        with self._lock:
            mounts = [self.workbench._public(r) for r in self.workbench.mounts.values()]
        result.update(sessionId=self.session_id, mounts=mounts)
        return result


    def _window(self, operation, params, context):
        if self._management_context is not None and context is self._management_context:
            # This signed context is held only by the trusted local shell. Reuse
            # the native provider's owner/profile checks without granting public
            # callers any window operations.
            provider = self._management_control.runtime.component_instance(self.window_id)
            return provider.call(operation, params, context)
        return super()._window(operation, params, context)

    def ensure_management_presentation(self):
        """Local GUI management entry; never exported to application QML."""
        self.actions.managementChanged.emit()
        window = self.actions._window
        if window is not None and window.isVisible():
            if self._management_context is None:
                self._management_context = self.user_access.context()
            self._view_state = self._window('show', {'handle': self.handle}, self._management_context)
            return self.status()
        self._management_context = self.user_access.context()
        return self.show(self._management_context)

    def open_extension_management(self):
        self.ensure_management_presentation()
        QMetaObject.invokeMethod(self.actions._window.rootObject(), 'showExtensionManagement', Qt.DirectConnection)

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
            self.workbench.reset_presentations(context)
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
        self.dispatcher.run(lambda: QTimer.singleShot(0, self.workbench.restore_pending))
        if self.application_host is not None:
            self.dispatcher.run(lambda: self.application_host.set_presentation_active(True))
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
        if self.application_host is not None:
            self.dispatcher.run(lambda: self.application_host.set_presentation_active(False))
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
        self.workbench.check_mounts()

    def set_cards(self, params, context):
        return self.workbench.set_cards(params, context)

    def mount(self, params, context):
        return self.workbench.mount(params, context)

    def unmount(self, params, context):
        return self.workbench.unmount(params, context)

    def set_layout(self, params, context):
        return self.workbench.set_layout(params, context)


def create_canvas(runtime=None, window_id='window', cleanup_port=None, collapse_delay=700, data_dir=None):
    return Canvas(runtime, window_id, cleanup_port, collapse_delay, data_dir)
