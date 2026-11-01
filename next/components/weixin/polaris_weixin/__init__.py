"""Weixin component capabilities; presentation imports Qt only on demand."""
import os
from pathlib import Path
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from .client import Client
from .credentials import CredentialStore
from .storage import ChatStore
from .controller import AgentController

WRITES = ('login', 'verify', 'connect', 'disconnect', 'logout', 'send', 'clear_messages')


def default_data_dir():
    base = (Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
            if os.name == 'nt' else Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share'))
    return base / 'polaris-weixin'


class Weixin(Component):
    def __init__(self, data_dir=None, transport=None, credentials=None, directory_id="collaboration", component_id="weixin", agent=None):
        super().__init__()
        directory = Path(data_dir) if data_dir is not None else default_data_dir()
        self._presentation = None
        self.client = Client(credentials or CredentialStore(directory / 'credentials.bin'),
                             ChatStore(directory / 'chats'), transport, self._changed)
        self.agent = AgentController(self.client, directory / "agent.json", self._changed, directory_id, component_id, agent)
        self.client.on_text = self.agent.receive
        self.client.on_invalidate = self.agent.invalidate
        self.client.on_account_changed = self.agent.reset_conversation
        self._lock = self.client._lock
        self.views = [{'id': 'main', 'adapter': 'qt-quick-item', 'title': '微信',
                       'create': 'create_view', 'release': 'release_view',
                       'permissions': [{'name': name, 'access': 'read'} for name in ('get', 'agent_settings', 'agent_catalog')] +
                                      [{'name': name, 'access': 'write'} for name in ('configure_agent', 'new_conversation')] +
                                      [{'target': directory_id, 'name': name, 'access': 'read'} for name in ('discover', 'describe')] +
                                      [{'name': name, 'access': 'write'} for name in WRITES]}]
        self.operation('get')(self.get)
        self.operation('agent_settings')(self.agent_settings)
        self.operation('agent_catalog')(self.agent_catalog)
        self.operation('configure_agent', access='write')(self.configure_agent)
        self.operation('new_conversation', access='write')(self.new_conversation)
        for name in WRITES:
            self.operation(name, access='write')(self.logout if name == 'logout' else getattr(self.client, name))
        self.operation('create_view', access='write')(self.create_view)
        self.operation('release_view', access='write')(self.release_view)

    def start(self, port):
        # The platform assigns the installation's actual component identity.
        self.agent.bind_identity(port.id)
        super().start(port)

    def logout(self):
        with self._lock:
            self.agent.reset_conversation()
            return self.client.logout()

    def _changed(self):
        if self._presentation is not None:
            self._presentation.changed.emit()

    def get(self):
        result = self.client.get()
        result['agent'] = self.agent_settings()
        return result

    def agent_settings(self):
        return self.agent.settings()

    def agent_catalog(self, ctx):
        return self.agent.catalog(ctx)

    def configure_agent(self, enabled, ctx, allowed=None):
        return self.agent.configure(enabled, allowed, ctx)

    def new_conversation(self):
        return self.agent.new_conversation()

    def describe(self):
        result = super().describe()
        for name in ('create_view', 'release_view'):
            result['operations'][name] = dict(result['operations'][name], profile='qt-native')
        return result

    def create_view(self, view, parent, ctx):
        if view != 'main':
            raise PlatformError('missing_view', '微信视图不存在')
        with self._lock:
            if self.port is None or self.client.stopped:
                raise PlatformError('component_unavailable', '微信组件未运行')
            if self._presentation is None:
                from .view import Presentation
                self._presentation = Presentation(self)
            presentation = self._presentation
        return presentation.create(parent, ctx, self.port)

    def release_view(self, handle):
        return self._presentation.release(handle) if self._presentation else {'released': False}

    def stop(self):
        self.client.stop()
        with self._lock:
            presentation, self._presentation = self._presentation, None
            if presentation is not None:
                presentation.closed = True
        if presentation is not None:
            presentation.close()
        super().stop()


def create(data_dir=None, transport=None, credentials=None, directory_id="collaboration", component_id="weixin", agent=None):
    return Weixin(data_dir, transport, credentials, directory_id, component_id, agent)
