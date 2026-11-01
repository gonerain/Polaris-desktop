from pathlib import Path
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Slot, QThread, QUrl, Qt, QRect
from PySide6.QtGui import QGuiApplication, QCursor
from PySide6.QtQuick import QQuickView
from ..component import Component
from ..protocol import PlatformError


class GuiDispatcher(QObject):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._execute)
        self.moveToThread(QGuiApplication.instance().thread())

    @Slot(object)
    def _execute(self, job):
        fn, event, box = job
        try:
            box.append((True, fn()))
        except Exception as exc:
            box.append((False, exc))
        finally:
            event.set()

    def run(self, fn):
        if QThread.currentThread() == self.thread():
            return fn()
        event, box = threading.Event(), []
        self.requested.emit((fn, event, box))
        if not event.wait(15):
            raise PlatformError('gui_unavailable', '界面暂时没有响应')
        ok, value = box[0]
        if not ok:
            raise value
        return value


class WindowHost(Component):
    """Owns native views. Local adapter methods are the published Qt-native port."""
    def __init__(self, runtime=None):
        super().__init__()
        if QGuiApplication.instance() is None:
            raise RuntimeError('Create QGuiApplication before desktop components')
        self._runtime = runtime
        self.dispatcher = GuiDispatcher()
        self._qt_profiles = {}
        self.running = False
        self._views = {}
        self._owners = {}
        self.operation('status')(lambda p, c: self.view_status(p.get('handle')) if p.get('handle') else self.status())
        self.operation('create', 'write')(self._create_operation)
        self.operation('update', 'write')(lambda p, c: self._owned(p, c, lambda: self.update_view(p['handle'], p.get('properties', {}))))
        self.operation('show', 'write')(lambda p, c: self._owned(p, c, lambda: self.show_view(p['handle'])))
        self.operation('hide', 'write')(lambda p, c: self._owned(p, c, lambda: self.hide_view(p['handle'])))
        self.operation('move', 'write')(lambda p, c: self._owned(p, c, lambda: self.move_view(p['handle'], p['x'], p['y'])))
        self.operation('release', 'write')(lambda p, c: self._owned(p, c, lambda: self.release_view(p['handle'])))

    def _owned(self, params, context, fn):
        if self._owners.get(params.get('handle')) != context.caller:
            raise PlatformError('view_owner', '此展示句柄属于其他组件')
        return fn()

    def _create_operation(self, params, context):
        profile = {}
        instance = None
        if self._runtime is not None:
            instance = self._runtime.status(context.caller)['instance']
            profile = self._qt_profiles.get((context.caller, instance), {})
        handle = self.create_view(params['source'], params.get('title', ''), tuple(params.get('size', [640, 480])), params.get('properties', {}), context=profile, options=params.get('options', {}), validate=lambda: self._validate_owner(context.caller, instance))
        self._owners[handle] = context.caller
        return {'handle': handle}

    def _validate_owner(self, owner, instance):
        if self._runtime is None: return
        current = self._runtime.status(owner)
        if current['instance'] != instance or current['state'] not in ('running', 'starting'):
            raise PlatformError('stale_instance', '展示请求所属实例已经停止')

    def register_qt_profile(self, client, bindings):
        """Authenticated native Qt profile registration; does not display a view."""
        if self._runtime is None:
            raise PlatformError('native_profile_unavailable', '窗口未配置原生界面接入')
        self._runtime.validate_client(client)
        if any(not isinstance(name, str) or not isinstance(value, QObject) for name, value in bindings.items()):
            raise PlatformError('invalid_qt_profile', '原生界面接入须使用Qt对象')
        self._qt_profiles = {key: value for key, value in self._qt_profiles.items() if key[0] != client.id}
        self._qt_profiles[(client.id, client.instance)] = dict(bindings)

    def unregister_qt_profile(self, client):
        if self._runtime is not None and self._runtime.status(client.id)['instance'] != client.instance:
            return
        self._qt_profiles.pop((client.id, client.instance), None)

    def release_owned(self, owner, handle):
        # Lifecycle cleanup port: only disposal, never grants display or access.
        if self._owners.get(handle) == owner:
            return self.release_view(handle)
        return {'released': False}


    def start(self, port):
        super().start(port)
        self.running = True

    def stop(self):
        self.running = False
        self.dispatcher.run(lambda: [self._destroy(k) for k in list(self._views)])
        self._qt_profiles.clear()
        super().stop()

    def _check(self):
        if not self.running:
            raise PlatformError('window_unavailable', '窗口承载未运行')

    def status(self):
        return {'available': self.running, 'views': list(self._views)}

    def create_view(self, source, title, size=(640, 480), properties=None, context=None, options=None, validate=None):
        self._check()
        def create():
            self._check()
            if validate: validate()
            view = QQuickView()
            view.setTitle(title)
            profile = dict(options or {})
            flags = view.flags()
            if profile.get('frameless'): flags |= Qt.FramelessWindowHint
            if profile.get('topmost'): flags |= Qt.WindowStaysOnTopHint
            view.setFlags(flags)
            if profile.get('transparent'):
                surface = view.format()
                surface.setAlphaBufferSize(8)
                view.setFormat(surface)
                view.setColor(Qt.transparent)
            view.setResizeMode(QQuickView.SizeRootObjectToView)
            for key, value in (context or {}).items():
                view.rootContext().setContextProperty(key, value)
            view.setSource(QUrl.fromLocalFile(str(Path(source).resolve())))
            if view.status() == QQuickView.Error:
                errors = '\n'.join(e.toString() for e in view.errors())
                import shiboken6
                shiboken6.delete(view)
                raise PlatformError('view_error', errors)
            view.resize(*size)
            screen = view.screen() or QGuiApplication.primaryScreen()
            bounds = screen.availableGeometry()
            x = profile.get('x', bounds.right() - size[0] - 32)
            y = profile.get('y', bounds.bottom() - size[1] - 32)
            view.setPosition(*self._clamp(view, x, y))
            for key, value in (properties or {}).items():
                view.rootObject().setProperty(key, value)
            key = uuid.uuid4().hex
            self._views[key] = view
            view.show()
            return key
        return self.dispatcher.run(create)

    def view_status(self, handle):
        if not self.running or handle not in self._views:
            return {'available': False, 'visible': False}
        def state():
            view = self._views[handle]
            return {'available': True, 'visible': view.isVisible(), 'x': view.x(), 'y': view.y(),
                    'width': view.width(), 'height': view.height(), 'transparent': view.color().alpha() == 0,
                    'frameless': bool(view.flags() & Qt.FramelessWindowHint),
                    'topmost': bool(view.flags() & Qt.WindowStaysOnTopHint),
                    'pointerInside': view.isVisible() and QRect(0, 0, view.width(), view.height()).contains(view.mapFromGlobal(QCursor.pos())),
                    'providerInstance': self.port.instance if self.port else None}
        return self.dispatcher.run(state)

    def _clamp(self, view, x, y):
        bounds = (view.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        return (max(bounds.left(), min(int(x), max(bounds.left(), bounds.right() - view.width() + 1))),
                max(bounds.top(), min(int(y), max(bounds.top(), bounds.bottom() - view.height() + 1))))

    def move_view(self, handle, x, y):
        self._check()
        def move():
            if handle not in self._views:
                raise PlatformError('stale_view', '展示窗口已经释放')
            view = self._views[handle]
            view.setPosition(*self._clamp(view, x, y))
            return self.view_status(handle)
        return self.dispatcher.run(move)

    def update_view(self, handle, properties):
        self._check()
        def update():
            if handle not in self._views:
                raise PlatformError('stale_view', '展示窗口已经释放')
            for key, value in properties.items():
                self._views[handle].rootObject().setProperty(key, value)
            return self.view_status(handle)
        return self.dispatcher.run(update)

    def show_view(self, handle):
        self._check()
        def show():
            if handle not in self._views:
                raise PlatformError('stale_view', '展示窗口已经释放')
            self._views[handle].show()
            if QGuiApplication.platformName() not in ('offscreen', 'minimal'):
                self._views[handle].raise_()
            return self.view_status(handle)
        return self.dispatcher.run(show)

    def hide_view(self, handle):
        self._check()
        def hide():
            if handle not in self._views:
                raise PlatformError('stale_view', '展示窗口已经释放')
            self._views[handle].hide()
            return self.view_status(handle)
        return self.dispatcher.run(hide)

    def _destroy(self, handle):
        view = self._views.pop(handle, None)
        self._owners.pop(handle, None)
        if view:
            view.close()
            # Dispose while the GUI event loop and QML context are still alive.
            import shiboken6
            shiboken6.delete(view)
        return {'released': True}

    def release_view(self, handle):
        return self.dispatcher.run(lambda: self._destroy(handle))


class ResourceCleanupPort:
    """Trusted disposal-only binding; resolves the current native provider per use."""
    def __init__(self, runtime, target):
        self._runtime, self._target = runtime, target

    def release_owned(self, owner, handle):
        try:
            provider = self._runtime.component_instance(self._target)
        except PlatformError:
            return {'released': False}
        if provider is None:
            return {'released': False}
        return provider.release_owned(owner, handle)


def create_window(runtime=None):
    return WindowHost(runtime)


class NativeQtProfilePort:
    """Native rendering binding. Window operations still use the authorized Client."""
    def __init__(self, runtime, target):
        self._runtime, self._target = runtime, target

    def register(self, client, bindings):
        provider = self._runtime.component_instance(self._target)
        if provider is None:
            raise PlatformError('window_unavailable', '窗口承载未运行')
        provider.register_qt_profile(client, bindings)

    def unregister(self, client):
        provider = self._runtime.component_instance(self._target)
        if provider is not None:
            provider.unregister_qt_profile(client)
