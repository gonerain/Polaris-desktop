"""Component-owned authority for explicit input in a trusted native view."""
import weakref
from PySide6.QtCore import QThread
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
import shiboken6
from ..protocol import PlatformError


class NativeViewInput:
    def __init__(self, runtime, client, parent):
        if not isinstance(parent, QQuickItem) or not shiboken6.isValid(parent):
            raise PlatformError('invalid_view', 'Local input requires a native view parent')
        self.__runtime, self.__client = runtime, client
        self.__parent = weakref.ref(parent)
        self.__item = None
        self.__closed = False

    def bind(self, item):
        parent = self.__parent()
        if self.__closed or self.__item is not None or item.parentItem() is not parent:
            raise PlatformError('invalid_view', 'Local input must belong to its native view')
        self.__item = weakref.ref(item)
        item.destroyed.connect(self.close)

    def close(self, *args):
        self.__closed = True

    def _check(self):
        from ..runtime import _active
        if _active.get() is not None:
            raise PlatformError('permission_denied', 'Local input cannot run inside a component request')
        app = QGuiApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise PlatformError('input_thread', '本机设置须来自界面线程')
        self.__runtime.validate_client(self.__client)
        parent = self.__parent()
        item = self.__item() if self.__item else None
        if (self.__closed or parent is None or item is None or not shiboken6.isValid(parent)
                or not shiboken6.isValid(item) or item.parentItem() is not parent or not item.isVisible()
                or item.window() is None or not item.window().isVisible()):
            raise PlatformError('stale_view', '本机视图已经关闭')

    def _context(self):
        self._check()
        from ..sdk import _LocalContext
        return _LocalContext(self.__client, self.__runtime.user_context(self.__client.id))

    def call(self, operation, params, *, permissions=(), revoked=()):
        """A provider's explicit native input is the authorization action itself.

        Only the fixed provider receives grants; no caller-supplied owner or
        restored/background context can use this port. Ordinary refresh uses
        the existing request context; polling never adds authority.
        """
        self._check()
        runtime, client = self.__runtime, self.__client
        selected = set(tuple(row) for row in permissions)
        removed = set(tuple(row) for row in revoked) - selected
        handles = {row: client.bind(*row) for row in selected}
        before = runtime.authorization.scope(client.id)
        installations = {row['id']: row['installation'] for row in runtime.snapshot()}
        removed = {(target, name) for target, name in removed if target in installations}
        touched = {handle.semantic[:3] for handle in handles.values()} | {
            (installations[target], 'operation', name) for target, name in removed}
        try:
            for target, name in removed:
                runtime.revoke(client.id, target, name)
            for target, name in selected:
                runtime.grant(client.id, target, name)
            return self._context().call(client.id, operation, params)
        except Exception:
            # Failed saves leave both the previous UI choice and grants in force.
            for key in runtime.authorization.scope(client.id):
                if key[:3] in touched and key not in before:
                    runtime.authorization.revoke(client.id, key)
            for key in before:
                if key[:3] in touched:
                    runtime.authorization.grant(client.id, key)
            raise
