"""Feishu text channel with explicitly bound schedule and Agent Bridge tools."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from uuid import uuid4


TOOLS = (
    ('scheduleGet', 'get', '查看日程', 'schedule'),
    ('scheduleTimeContext', 'time_context', '时间信息', 'schedule'),
    ('scheduleTasks', 'tasks', '查询任务', 'schedule'),
    ('scheduleAdd', 'add', '新增任务', 'schedule'),
    ('scheduleUpdate', 'update', '更新任务', 'schedule'),
    ('scheduleDelete', 'delete', '删除任务', 'schedule'),
    ('scheduleUndoDelete', 'undo_delete', '恢复删除', 'schedule'),
    ('scheduleAddSubtask', 'add_subtask', '新增子任务', 'schedule'),
    ('scheduleUpdateSubtask', 'update_subtask', '更新子任务', 'schedule'),
    ('scheduleDeleteSubtask', 'delete_subtask', '删除子任务', 'schedule'),
    ('scheduleReorder', 'reorder', '调整排序', 'schedule'),
    ('scheduleMoveOverdue', 'move_overdue', '迁移逾期任务', 'schedule'),
    ('scheduleOrganizeDay', 'organize_day', '整理当日日程', 'schedule'),
    ('bridgeSessions', 'sessions', '查询会话', 'bridge'),
    ('bridgeStatus', 'status', '查询状态', 'bridge'),
    ('bridgeResult', 'result', '读取结果', 'bridge'),
    ('bridgeDelivery', 'delivery', '查询投递', 'bridge'),
    ('bridgeMark', 'mark', '标记会话', 'bridge'),
    ('bridgeUnmark', 'unmark', '取消标记', 'bridge'),
    ('bridgeSend', 'send', '发送任务', 'bridge'),
    ('bridgeRequests', 'requests', '查询请求', 'bridge'),
)
TOOL_GROUPS = (('schedule', '日程'), ('bridge', 'Agent Bridge'))

class Service:
    interval = 1.2

    def __init__(self, context):
        self.context = context
        self.path = Path(context.data_directory) / 'state.json'
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.thread = None
        self.running = False
        self.error = ''
        self.feishu = {}
        self.agent = {}
        self.data = dict(cursor=None, tasks=[], conversations={})
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        for task in self.data['tasks']:
            if task['state'] == 'sending':
                task.update(state='unknown', error='上次发送在应用停止前未返回结果，请先在飞书中核对。')
            elif task['state'] == 'generating':
                task.update(state='failed', error='上次生成在应用停止前未完成，可手动继续。')
        self._save()
        self._publish()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def _publish(self):
        with self.lock:
            bindings = self.context.bindings
            attention = {'failed', 'send_failed', 'unknown'}
            visible = [task for index, task in enumerate(self.data['tasks'])
                       if index >= len(self.data['tasks']) - 40 or task['state'] in attention]
            tool_groups = []
            for key, title in TOOL_GROUPS:
                entries = [tool for tool in TOOLS if tool[3] == key]
                tool_groups.append(dict(title=title,
                    instanceId=bindings.get(entries[0][0], {}).get('instanceId', ''),
                    labels=[tool[2] for tool in entries]))
            self.context.publish(dict(toolGroups=tool_groups, running=self.running, error=self.error,
                initialized=self.data['cursor'] is not None, cursor=self.data['cursor'],
                feishuInstance=bindings.get('feishuStatus', {}).get('instanceId', ''),
                agentInstance=bindings.get('agentStatus', {}).get('instanceId', ''),
                feishu=deepcopy(self.feishu), agent=deepcopy(self.agent),
                tasks=deepcopy(list(reversed(visible)))))

    def _check_bindings(self):
        bindings = self.context.bindings
        groups = [('飞书机器人', ('feishuStatus', 'feishuRead', 'feishuReply')),
                  ('Polaris Agent', ('agentStatus', 'agentReply'))]
        groups.extend((title, tuple(alias for alias, op, label, group in TOOLS if group == key))
                      for key, title in TOOL_GROUPS)
        for title, aliases in groups:
            identities = [bindings[alias]['instanceId'] for alias in aliases]
            if len(set(identities)) != 1:
                raise ValueError('请将' + title + '的全部能力连接到同一个组件实例')

    def _allowed_tools(self):
        bindings = self.context.bindings
        return [dict(target=bindings[alias]['target'], operation=bindings[alias]['operation'])
                for alias, op, label, group in TOOLS]

    def start(self):
        self._check_bindings()
        self.running = True
        self._publish()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.wake.set()
        self._publish()
        if self.thread is not None:
            self.thread.join()

    def _stopped(self):
        return not self.running or self.context.stopped.is_set()

    def _statuses(self):
        self.feishu = self.context.call('feishuStatus', {})
        if self.feishu['connectionState'] == 'connecting':
            return False
        if self.feishu['connectionState'] != 'connected':
            raise ValueError(self.feishu.get('lastError') or '飞书机器人尚未连接，请在组件中连接后手动继续。')
        self.agent = self.context.call('agentStatus', {})
        if not self.agent['ready']:
            raise ValueError(self.agent.get('detail') or 'Polaris Agent 尚未就绪，请处理后手动继续。')
        return True

    def _initialize_cursor(self):
        cursor = 0
        while not self._stopped():
            batch = self.context.call('feishuRead', dict(after=cursor, limit=500))
            cursor = batch['nextCursor']
            if len(batch['items']) < 500:
                with self.lock:
                    self.data['cursor'] = cursor
                    self._save()
                return

    @staticmethod
    def _incoming(message):
        if message['direction'] not in ('inbound', 'incoming'):
            return False
        return message.get('messageType') in ('text', 'post') and bool(message.get('text', '').strip())

    def _receive(self):
        batch = self.context.call('feishuRead', dict(after=self.data['cursor'], limit=500))
        with self.lock:
            known = {task['messageId'] for task in self.data['tasks']}
            for message in batch['items']:
                if not self._incoming(message) or message['messageId'] in known:
                    continue
                normalized = message.get('normalized') or {}
                thread_id = (normalized.get('conversation') or {}).get('thread_id') or message.get('threadId') or ''
                key = json.dumps([message['chatId'], thread_id], ensure_ascii=False)
                conversation = self.data['conversations'].setdefault(key, uuid4().hex)
                self.data['tasks'].append(dict(id=uuid4().hex, messageId=message['messageId'],
                    chatId=message['chatId'], threadId=thread_id, conversation=conversation,
                    text=message['text'], answer='', turn='', state='pending', error=''))
                known.add(message['messageId'])
            self.data['cursor'] = batch['nextCursor']
            self._save()

    def _transition(self, task, **values):
        with self.lock:
            task.update(values)
            self._save()
        self._publish()

    def _process(self, task):
        if task['state'] == 'pending':
            if len(task['text']) > 8000:
                self._transition(task, state='failed', error='正文超过 Agent 的 8000 字限制，请在飞书中发送较短消息。')
                return
            self._transition(task, state='generating', error='')
            try:
                result = self.context.call('agentReply', dict(text=task['text'], conversation=task['conversation'], allowed=self._allowed_tools()))
                self._transition(task, state='ready', answer=result['text'], turn=result['turn'])
            except Exception as error:
                self._transition(task, state='failed', error=str(error))
                return
        if self._stopped():
            return
        self._transition(task, state='sending', error='')
        try:
            result = self.context.call('feishuReply', dict(message_id=task['messageId'], text=task['answer'], reply_in_thread=bool(task['threadId'])))
            self._transition(task, state='done', sentMessageId=result['messageId'])
        except Exception as error:
            code = getattr(error, 'code', '')
            rejected = code in {'invalid_params', 'invalid_reply', 'message_missing', 'not_connected',
                'permission_denied', 'permission_required', 'application_binding_unavailable', 'application_binding_unsupported', 'application_closed',
                'feishu_format_error', 'feishu_target_revoked', 'feishu_rate_limited', 'feishu_permission_denied', 'feishu_not_connected'}
            raw = code[7:] if code.startswith('feishu_') else ''
            rejected = rejected or raw.isdigit() and not 500 <= int(raw) <= 599
            if rejected:
                self._transition(task, state='send_failed', error='发送被拒绝：' + str(error))
            else:
                self._transition(task, state='unknown', error='发送结果未确认：' + str(error) + '。请先在飞书中核对，再选择处理方式。')

    def _loop(self):
        try:
            self._statuses()
        except Exception as error:
            self.error = str(error)
            self._publish()
        while not self._stopped():
            if not self.error:
                try:
                    if not self._statuses():
                        self._publish()
                        self.wake.wait(self.interval)
                        self.wake.clear()
                        continue
                    if self.data['cursor'] is None:
                        self._initialize_cursor()
                    if self._stopped():
                        break
                    self._receive()
                    # Preserve order within each chat/topic when an earlier task needs attention.
                    blocked = set()
                    for task in self.data['tasks']:
                        conversation = task['conversation']
                        if task['state'] in ('failed', 'send_failed', 'unknown'):
                            blocked.add(conversation)
                        elif task['state'] in ('pending', 'ready') and conversation not in blocked:
                            if self._stopped():
                                break
                            self._process(task)
                            if task['state'] in ('failed', 'send_failed', 'unknown'):
                                blocked.add(conversation)
                    self._publish()
                except Exception as error:
                    self.error = str(error)
                    self._publish()
            self.wake.wait(self.interval)
            self.wake.clear()

    def handle(self, command, params):
        if command == 'continue':
            self._statuses()
            self.error = ''
            self.wake.set()
            self._publish()
            return {'success': True}
        if command not in ('retry', 'skip', 'confirm_sent', 'resend'):
            raise ValueError('未知操作')
        with self.lock:
            task = next(task for task in self.data['tasks'] if task['id'] == params['taskId'])
            if command == 'retry' and task['state'] == 'failed':
                task.update(state='pending', error='')
            elif command == 'skip' and task['state'] == 'failed':
                task.update(state='skipped', error=task['error'])
            elif command == 'confirm_sent' and task['state'] == 'unknown':
                task.update(state='done', error='', manuallyConfirmed=True)
            elif command == 'resend' and task['state'] in ('unknown', 'send_failed'):
                task.update(state='ready', error='')
            else:
                raise ValueError('此请求当前不支持所选操作')
            self._save()
        self.wake.set()
        self._publish()
        return {'success': True}


def create(context):
    return Service(context)
