"""Optional trusted local management interface, separate from public operations.

A running management provider may expose local_management_control() returning
an object with request_mount, report_notice and refresh methods. Providers that
only implement show/hide/status remain valid; they cannot approve native mounts.
"""
import sys
from ..protocol import PlatformError


class ManagementControlPort:
    def __init__(self, runtime):
        self.runtime = runtime

    def _provider(self):
        identity = self.runtime.roles.get('desktop_management', 'manager')
        try:
            if self.runtime.status(identity)['state'] == 'running':
                return self.runtime.component_instance(identity)
        except PlatformError as error:
            if error.code != 'not_installed':
                raise
        return None

    def show(self):
        """Trusted recovery entry: invoke the provider's public show operation.

        This local management action carries no delegated component authority.
        It neither grants permissions nor runs on behalf of a mounted plugin.
        """
        provider = self._provider()
        if provider is None:
            raise PlatformError('management_unavailable', '组件管理未运行')
        return provider.call('show', {}, None)

    def _control(self):
        provider = self._provider()
        if provider is None:
            return None
        factory = getattr(provider, 'local_management_control', None)
        return factory() if callable(factory) else None

    def request_mount(self, requester, target, view_id, on_finished=None):
        control = self._control()
        if control is None:
            raise PlatformError('management_unavailable', '组件管理不提供本机挂载授权')
        return control.request_mount(requester, target, view_id, on_finished)

    def report_notice(self, message):
        control = self._control()
        if control is None:
            print(str(message), file=sys.stderr)
        else:
            control.report_notice(str(message))

    def refresh(self):
        control = self._control()
        if control is not None:
            control.refresh()
