"""A directory plugin owning both a counter and its native Qt Quick view."""
from pathlib import Path
import threading
import uuid
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlEngine, qmlContext
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
import shiboken6


class _Changes(QObject):
    changed = Signal()


class _CounterBridge(QObject):
    changed = Signal()
    errorChanged = Signal()

    def __init__(self, component, context, parent):
        super().__init__(parent)
        self.component, self.context = component, context
        self._error = ''
        component._changes.changed.connect(self.changed)

    @Property(int, notify=changed)
    def value(self):
        return self.component.value()

    @Property(str, notify=errorChanged)
    def lastError(self):
        return self._error

    def _change(self, delta):
        try:
            # Buttons retain the creating request's scope; they cannot acquire new grants.
            self.context.call(self.component.port.id, 'increment', {'delta': delta})
        except PlatformError as error:
            self._error = error.message
        else:
            self._error = ''
        self.errorChanged.emit()

    @Slot()
    def increase(self):
        self._change(1)

    @Slot()
    def decrease(self):
        self._change(-1)


class Counter(Component):
    def __init__(self):
        super().__init__()
        self._value = 0
        self._lock = threading.RLock()
        self._dispatcher = None
        self._changes = None
        self._views = {}
        self.views = [{'id': 'main', 'adapter': 'qt-quick-item', 'title': '计数器',
                       'create': 'create_view', 'release': 'release_view',
                       'permissions': [{'name': 'increment', 'access': 'write'}]}]
        self.operation('get')(self.get)
        self.operation('increment', access='write')(self.increment)
        self.operation('create_view', access='write')(self.create_view)
        self.operation('release_view', access='write')(self.release_view)

    def describe(self):
        result = super().describe()
        for name in ('create_view', 'release_view'):
            result['operations'][name] = dict(result['operations'][name], profile='qt-native')
        return result

    def _gui(self, function):
        if self._dispatcher is None:
            from polaris_platform.desktop import GuiDispatcher
            self._dispatcher = GuiDispatcher()
        return self._dispatcher.run(function)

    def value(self):
        with self._lock:
            return self._value

    def get(self):
        return {'value': self.value()}

    def increment(self, delta=1):
        if not isinstance(delta, int) or isinstance(delta, bool) or delta not in (-1, 1):
            raise ValueError('delta must be +1 or -1')
        with self._lock:
            self._value += delta
            value = self._value
        if self._changes is not None:
            self._gui(self._changes.changed.emit)
        return {'value': value}

    def create_view(self, view, parent, ctx):
        if view != 'main':
            raise PlatformError('missing_view', view)
        def create():
            if self._changes is None:
                self._changes = _Changes()
            engine = qmlEngine(parent)
            if engine is None:
                raise PlatformError('view_error', 'Native parent has no QML engine')
            context = QQmlContext(qmlContext(parent), parent)
            bridge = _CounterBridge(self, ctx, context)
            context.setContextProperty('counterModel', bridge)
            definition = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(__file__).with_name('Counter.qml'))))
            item = definition.create(context)
            if item is None:
                errors = '\n'.join(error.toString() for error in definition.errors())
                context.deleteLater()
                raise PlatformError('view_error', errors)
            context.setParent(item)
            item.setParentItem(parent)
            item.setParent(parent)
            handle = uuid.uuid4().hex
            self._views[handle] = (item, context, bridge, definition)
            def destroyed():
                self._views.pop(handle, None)
            item.destroyed.connect(destroyed)
            return {'handle': handle, 'item': item}
        return self._gui(create)

    def release_view(self, handle):
        return self._gui(lambda: self._release(handle))

    def _release(self, handle):
        resource = self._views.pop(handle, None)
        if resource is None:
            return {'released': False}
        item = resource[0]
        if shiboken6.isValid(item):
            item.setVisible(False)
            item.deleteLater()
        return {'released': True}

    def stop(self):
        if self._views:
            self._gui(lambda: [self._release(handle) for handle in list(self._views)])
        super().stop()


def create():
    return Counter()
