"""Trusted local user input boundary; never exposed in a provider's QML context."""
from ..protocol import PlatformError


class DesktopUserAccess:
    def __init__(self, runtime, component_id=None):
        self._runtime = runtime
        self._subject = component_id

    def bind(self, component_id):
        if self._subject is not None and self._subject != component_id:
            raise PlatformError('input_identity', '本机输入身份不匹配')
        self._subject = component_id

    def context(self, component_id=None):
        """Called by a real local input slot; delayed work retains its returned context."""
        from PySide6.QtCore import QThread
        from PySide6.QtGui import QGuiApplication
        if QThread.currentThread() != QGuiApplication.instance().thread():
            raise PlatformError('input_thread', '本机输入须来自界面线程')
        subject = component_id or self._subject
        if not self._subject or subject != self._subject:
            raise PlatformError('input_identity', '本机输入身份不匹配')
        return self._runtime.user_context(subject)

    def snapshot(self):
        return self._runtime.snapshot()

    def status(self, target):
        return self._runtime.status(target)

    def data_directory(self):
        return self._runtime.component_data_directory(self._subject)

    def prepare_mount(self, target, descriptor, on_finished=None):
        # A picker click opens the trusted approval UI; it never grants by itself.
        self.context()  # Verify this is the bound local GUI input entry.
        manager_id = self._runtime.roles.get('desktop_management', 'manager')
        manager = self._runtime.component_instance(manager_id)
        if manager is None:
            raise PlatformError('management_unavailable', '组件管理未运行')
        manager.show()
        return manager.bridge.request_mount(self._subject, target, descriptor['id'], on_finished)
