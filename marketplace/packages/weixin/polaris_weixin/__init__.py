"""Weixin component capabilities; presentation imports Qt only on demand."""
import os
import json
import re
import shutil
import threading
import uuid
from types import SimpleNamespace
from pathlib import Path
from polaris_platform.sdk import Component
from polaris_platform.protocol import PlatformError
from .client import Client
from .credentials import CredentialStore
from .storage import ChatStore, atomic_write
from .controller import AgentController
from .completion import CompletionAdapter
from .attachments import AttachmentStore
from .interactions import HumanReplies

WRITES = ('login', 'verify', 'connect', 'disconnect', 'logout', 'send', 'clear_messages')


def default_data_dir():
    base = (Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
            if os.name == 'nt' else Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share'))
    return base / 'polaris-weixin'


class Weixin(Component):
    def __init__(self, data_dir=None, transport=None, credentials=None, directory_id="collaboration", component_id="weixin"):
        super().__init__()
        directory = Path(data_dir) if data_dir is not None else default_data_dir()
        self._presentation = None
        self._directory, self._transport = directory, transport
        self._directory_id, self._component_id = directory_id, component_id
        self._lock = threading.RLock()
        self._robots = {}
        self._robot_path = directory / 'robots.json'
        if self._robot_path.exists():
            try:
                data = json.loads(self._robot_path.read_text('utf8'))
                rows, selected = data['robots'], data['selected']
                if (data.get('version') != 1 or not isinstance(rows, list) or not rows
                        or any(not isinstance(r, dict) or not isinstance(r.get('id'), str)
                            or not re.fullmatch(r'default|[0-9a-f]{32}', r['id'])
                            or not isinstance(r.get('name'), str) or not 1 <= len(r['name']) <= 60 for r in rows)
                        or len({r['id'] for r in rows}) != len(rows)
                        or selected not in {r['id'] for r in rows}):
                    raise ValueError()
            except (ValueError, KeyError, TypeError, IndexError):
                raise PlatformError('invalid_state', '机器人列表无法读取，请检查 robots.json')
        else:
            rows, selected = [{'id': 'default', 'name': '机器人 1'}], 'default'
        for row in rows:
            self._robots[row['id']] = self._make_robot(row['id'], row['name'], credentials if row['id'] == 'default' else None)
        self._selected = selected
        self.views = [{'id': 'main', 'adapter': 'qt-quick-item', 'title': '微信',
                       'create': 'create_view', 'release': 'release_view',
                       'permissions': [{'name': name, 'access': 'read'} for name in ('get', 'agent_settings', 'agent_catalog')] +
                                      [{'name': name, 'access': 'write'} for name in ('configure_agent', 'new_conversation', 'complete_agent_run', 'receive_agent_request', 'agent_control')] +
                                      [{'target': directory_id, 'name': name, 'access': 'read'} for name in ('discover', 'describe')] +
                                      [{'name': name, 'access': 'write'} for name in WRITES + ('add_robot', 'select_robot', 'remove_robot')]}]
        self.operation('get')(self.get)
        for name in ('add_robot', 'select_robot', 'remove_robot'):
            self.operation(name, access='write')(getattr(self, name))
        self.operation('save_attachment', access='write')(self.save_attachment)
        self.operation('write_file', access='write')(self.write_file)
        self.operation('read_file')(self.read_file)
        self.operation('agent_settings')(self.agent_settings)
        self.operation('agent_catalog')(self.agent_catalog)
        self.operation('configure_agent', access='write')(self.configure_agent)
        self.operation('new_conversation', access='write')(self.new_conversation)
        self.operation('complete_agent_run', access='write')(self.complete_agent_run)
        self.operation('receive_agent_request', access='write')(self.receive_agent_request)
        self.operation('agent_control', access='write')(self.agent_control)
        for name in WRITES:
            self.operation(name, access='write')(getattr(self, name))
        self.operation('create_view', access='write')(self.create_view)
        self.operation('release_view', access='write')(self.release_view)

    def _make_robot(self, identity, name, credentials=None):
        directory = self._directory if identity == 'default' else self._directory / 'robots' / identity
        robot = SimpleNamespace(id=identity, name=name, directory=directory)
        robot.client = Client(credentials or CredentialStore(directory / 'credentials.bin'),
                              ChatStore(directory / 'chats'), self._transport, self._changed)
        robot.attachments = AttachmentStore()
        robot.client.attachments = robot.attachments
        robot.agent = AgentController(robot.client, directory / 'agent.json', self._changed,
                                      self._directory_id, self._component_id, robot_id=identity)
        robot.completions = CompletionAdapter(robot.client, directory / 'agent-completions.json', self._component_id)
        robot.agent.completions = robot.completions
        robot.interactions = HumanReplies(robot.client, directory / 'agent-interactions.json', robot.completions)
        robot.client.on_text = lambda text, timestamp: self._receive_text(text, timestamp, robot)
        robot.client.on_invalidate = robot.agent.invalidate
        robot.client.on_account_changed = robot.agent.reset_conversation
        robot.client.local_bot_tokens = lambda: self._local_bot_tokens(robot.id)
        return robot

    def _local_bot_tokens(self, robot_id):
        # The server uses other saved bindings to recognize a previously connected bot.
        # Leave out this slot so an expired binding can still refresh its own token.
        with self._lock:
            robots = list(self._robots.values())
        tokens = []
        for robot in reversed(robots):
            token = robot.client.account.get('token')
            if robot.id != robot_id and token and token not in tokens:
                tokens.append(token)
                if len(tokens) == 10:
                    break
        return tokens

    def _robot(self, robot_id=None):
        with self._lock:
            identity = self._selected if robot_id is None else robot_id
            if not isinstance(identity, str) or identity not in self._robots:
                raise PlatformError('missing_robot', '机器人不存在')
            return self._robots[identity]

    @property
    def client(self):
        return self._robot().client

    @property
    def agent(self):
        return self._robot().agent

    @property
    def attachments(self):
        return self._robot().attachments

    @property
    def completions(self):
        return self._robot().completions

    @property
    def interactions(self):
        return self._robot().interactions

    def _save_robots(self):
        atomic_write(self._robot_path, json.dumps(dict(version=1, selected=self._selected,
            robots=[dict(id=r.id, name=r.name) for r in self._robots.values()]), ensure_ascii=False).encode())

    def _start_robot(self, robot):
        robot.agent.bind_identity(self.port.id)
        robot.completions.identity = self.port.id
        robot.agent.bind_resume(lambda: self.resume_task(robot.agent.task_name))
        if robot.client.account and not robot.client.account.get('expired'):
            robot.client.connect()
            robot.agent.resume()

    def start(self, port):
        super().start(port)
        for robot in self._robots.values():
            self._start_robot(robot)

    def add_robot(self, name=''):
        if not isinstance(name, str) or len(name.strip()) > 60:
            raise PlatformError('invalid_params', '机器人名称最多 60 字')
        with self._lock:
            identity, previous = uuid.uuid4().hex, self._selected
            robot = self._make_robot(identity, name.strip() or '机器人 ' + str(len(self._robots) + 1))
            self._robots[identity], self._selected = robot, identity
            try:
                self._save_robots()
            except Exception:
                self._robots.pop(identity)
                self._selected = previous
                robot.client.stop()
                raise
        if self.port is not None:
            self._start_robot(robot)
        self._changed()
        return {'robotId': identity}

    def select_robot(self, robot_id):
        with self._lock:
            robot = self._robot(robot_id)
            previous, self._selected = self._selected, robot.id
            try:
                self._save_robots()
            except Exception:
                self._selected = previous
                raise
        self._changed()
        return {'robotId': robot.id}

    def remove_robot(self, robot_id, ctx):
        with self._lock:
            robot = self._robot(robot_id)
            if len(self._robots) == 1:
                raise PlatformError('invalid_state', '至少保留一个机器人，可退出登录解除绑定')
            # Revoke its saved automatic task before removing its private data.
            ctx.forget_task(robot.agent.task_name)
            previous = self._selected
            rows = dict(self._robots)
            del self._robots[robot.id]
            if self._selected == robot.id:
                self._selected = next(iter(self._robots))
            try:
                self._save_robots()
            except Exception:
                self._robots, self._selected = rows, previous
                raise
        robot.client.stop()
        robot.client.logout()
        if robot.id == 'default':
            for filename in ('agent.json', 'agent-completions.json', 'agent-interactions.json'):
                (robot.directory / filename).unlink(missing_ok=True)
            if (robot.directory / 'chats').exists():
                shutil.rmtree(robot.directory / 'chats')
        elif robot.directory.exists():
            shutil.rmtree(robot.directory)
        self._changed()
        return {'removed': True, 'robotId': robot.id}

    def login(self, robot_id=None):
        return self._robot(robot_id).client.login()

    def verify(self, code, robot_id=None):
        return self._robot(robot_id).client.verify(code)

    def connect(self, robot_id=None):
        return self._robot(robot_id).client.connect()

    def disconnect(self, robot_id=None):
        return self._robot(robot_id).client.disconnect()

    def send(self, text, robot_id=None):
        return self._robot(robot_id).client.send(text)

    def clear_messages(self, robot_id=None):
        return self._robot(robot_id).client.clear_messages()

    def logout(self, robot_id=None):
        robot = self._robot(robot_id)
        with robot.client._lock:
            robot.agent.reset_conversation()
            return robot.client.logout()

    def _changed(self):
        if self._presentation is not None:
            self._presentation.changed.emit()

    def _receive_text(self, text, timestamp, robot=None):
        robot = robot or self._robot()
        robot.agent.resume()
        if not robot.interactions.handle(text, timestamp, robot.agent.ctx):
            robot.agent.receive(text, timestamp)

    def receive_agent_request(self, notification_id, result, ctx):
        source = getattr(getattr(ctx, 'context', None), 'caller', None)
        return self._callback_robot(notification_id).interactions.receive(notification_id, result, source)

    def get(self, ctx=None, robot_id=None):
        robot = self._robot(robot_id)
        if ctx is not None:
            robot.agent.resume()
            robot.agent.refresh(robot.agent.ctx or ctx)
        result = robot.client.get()
        result['agent'] = robot.agent.settings()
        with self._lock:
            robots = list(self._robots.values())
        result['robotId'] = robot.id
        result['robots'] = [dict(id=r.id, name=r.name, **{k: v for k, v in r.client.get().items()
            if k in ('state', 'hasAccount', 'accountId', 'userId')}) for r in robots]
        return result

    def save_attachment(self, attachment_id, robot_id=None):
        robot = self._robot(robot_id)
        account = (robot.client.account.get('botId'), robot.client.account.get('userId'))
        return robot.attachments.save(attachment_id, account, robot.client.cancel)

    def write_file(self, name, content, encoding='utf-8', robot_id=None):
        return self._robot(robot_id).attachments.write(name, content, encoding)

    def read_file(self, file_id, encoding='utf-8', offset=0, limit=65536, robot_id=None):
        return self._robot(robot_id).attachments.read(file_id, encoding, offset, limit)

    def agent_settings(self, ctx=None, robot_id=None):
        agent = self._robot(robot_id).agent
        return agent.refresh(agent.ctx or ctx) if ctx is not None else agent.settings()

    def agent_catalog(self, ctx, robot_id=None):
        return self._robot(robot_id).agent.catalog(ctx)

    def configure_agent(self, enabled, ctx, allowed=None, robot_id=None):
        return self._robot(robot_id).agent.configure(enabled, allowed, ctx)

    def agent_control(self, turn, action, ctx, target=None, metadata=None, arguments=None):
        with self._lock:
            robots = list(self._robots.values())
        robot = next((r for r in robots if turn in r.agent.turns), None)
        if robot is None:
            raise PlatformError('denied', '委托轮次不存在或已失效')
        return robot.agent.control(turn, action, ctx, target, metadata, arguments)

    def new_conversation(self, robot_id=None):
        return self._robot(robot_id).agent.new_conversation()

    def _callback_robot(self, notification_id):
        with self._lock:
            robot = next((r for r in self._robots.values() if notification_id in r.completions.records), None)
        if robot is None:
            raise PlatformError('invalid_params', '任务通知不存在或机器人已删除')
        return robot

    def complete_agent_run(self, notification_id, result, ctx):
        source = getattr(getattr(ctx, 'context', None), 'caller', None)
        return self._callback_robot(notification_id).completions.receive(notification_id, result, source)

    def describe(self):
        result = super().describe()
        result['operations']['agent_control'].update(modelCallable=False, description='本轮委托回调，校验来源与轮次。')
        for name, title, description in (
            ('save_attachment', '保存微信附件', '将本账号收到的图片或文件保存到组件临时目录，返回 file_id、path、name、size、mime。'),
            ('write_file', '写入临时文件', '仅在本组件临时目录创建文件；name 为文件名，content 为正文，encoding 为 utf-8 或 base64。返回本地绝对路径。'),
            ('read_file', '读取临时文件', '按 file_id 读取本组件创建的文件；可指定 encoding、offset、limit（最多 1 MiB）。临时目录清理后文件失效。')):
            result['operations'][name].update(title=title, description=description)
        for name, properties, required in (
            ('save_attachment', {'attachment_id':{'type':'string'}}, ['attachment_id']),
            ('write_file', {'name':{'type':'string'},'content':{'type':'string'},'encoding':{'type':'string','enum':['utf-8','base64']}}, ['name','content']),
            ('read_file', {'file_id':{'type':'string'},'encoding':{'type':'string','enum':['utf-8','base64']},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':1048576}}, ['file_id'])):
            properties['robot_id'] = {'type': 'string', 'description': '机器人 ID，省略时使用当前选中机器人'}
            result['operations'][name]['parameters']={'type':'object','properties':properties,'required':required,'additionalProperties':False}
        result['operations']['complete_agent_run'].update(title='接收任务结果',
            description='将本组件发起任务的确定结束结果直接通知绑定者，不调用模型；按任务去重。')
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
        return presentation.create(parent, ctx, self.port, ctx.local_view_input(parent))

    def release_view(self, handle):
        return self._presentation.release(handle) if self._presentation else {'released': False}

    def stop(self):
        for robot in list(self._robots.values()):
            robot.client.stop()
        with self._lock:
            presentation, self._presentation = self._presentation, None
            if presentation is not None:
                presentation.closed = True
        if presentation is not None:
            presentation.close()
        super().stop()


def create(data_dir=None, transport=None, credentials=None, directory_id="collaboration", component_id="weixin"):
    return Weixin(data_dir, transport, credentials, directory_id, component_id)
