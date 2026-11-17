"""Durable Feishu channel for one existing Codex CLI session and Bridge outputs."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from uuid import uuid4


REJECTED = {'invalid_params', 'busy', 'not_running', 'unavailable', 'not_configured',
    'permission_required', 'permission_denied', 'application_alias_missing', 'application_binding_missing',
    'application_binding_unavailable', 'application_binding_unsupported', 'application_closed',
    'not_connected', 'invalid_reply', 'message_missing', 'feishu_not_connected',
    'feishu_format_error', 'feishu_target_revoked', 'feishu_rate_limited', 'feishu_permission_denied'}


def rejected(error):
    code = getattr(error, 'code', '')
    raw = code[7:] if code.startswith('feishu_') else ''
    return code in REJECTED or raw.isdigit() and not 500 <= int(raw) <= 599


class Service:
    interval = 1.2

    def __init__(self, context):
        self.context = context
        self.path = Path(context.data_directory) / 'state.json'
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.thread = None
        self.running = False
        self.codex = {}
        self.issues = {}
        self.paused = set()
        self.data = dict(schemaVersion=2, cursor=None, channel=None, inputs=[], outputs=[], seenCodex=None, legacy=None)
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if 'schemaVersion' not in saved:
                self.data.update(cursor=saved['cursor'], legacy=saved)
            elif saved['schemaVersion'] == 2:
                self.data = saved
            else:
                raise ValueError('不支持的飞书 Agent 数据版本')
        for queue in ('inputs', 'outputs'):
            for item in self.data[queue]:
                if item['state'] == 'sending':
                    item.update(state='unknown', error='上次投递未返回结果，请核对后再决定是否重发。')
        self._save()
        self._publish()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def _attention(self):
        rows = []
        for kind in ('inputs', 'outputs'):
            for item in self.data[kind]:
                if item['state'] in ('failed', 'unknown'):
                    rows.append(dict(id=item['id'], kind=kind, state=item['state'], text=item['text'], error=item['error']))
        if self.data['legacy'] is not None:
            for item in self.data['legacy']['tasks']:
                if item['state'] not in ('done', 'skipped') and not item.get('migratedTo'):
                    rows.append(dict(id=item['id'], kind='legacy', state=item['state'], text=item['text'],
                                     error='旧链路任务已保留，尚未交给 Codex。' + item.get('error', '')))
        return rows

    def _publish(self):
        with self.lock:
            self.context.publish(dict(running=self.running, connected=self.data['channel'] is not None,
                session=self.codex.get('cwd', ''), sessionId=self.codex.get('threadId'),
                connection=self.codex.get('connection', 'waiting'),
                pending=sum(item['state'] == 'queued' for kind in ('inputs', 'outputs') for item in self.data[kind]),
                issues=list(self.issues.values()), attention=self._attention(),
                callback=dict(target=self.context.application_id, operation='bridge_output', params={})))

    def _stopped(self):
        return not self.running or self.context.stopped.is_set()

    def start(self):
        self.running = True
        self._publish()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.wake.set()
        if self.thread is not None:
            self.thread.join()
        self._publish()

    @staticmethod
    def _channel(message):
        normalized = message.get('normalized') or {}
        thread = (normalized.get('conversation') or {}).get('thread_id') or message.get('threadId') or ''
        return dict(chatId=message['chatId'], threadId=thread, messageId=message['messageId'])

    @staticmethod
    def _same_channel(first, second):
        return (first['chatId'], first['threadId']) == (second['chatId'], second['threadId'])

    def _receive(self):
        if self.data['cursor'] is None:
            cursor = 0
            while not self._stopped():
                batch = self.context.call('feishuRead', dict(after=cursor, limit=500))
                cursor = batch['nextCursor']
                if len(batch['items']) < 500:
                    with self.lock:
                        self.data['cursor'] = cursor
                        self._save()
                    return
            return
        batch = self.context.call('feishuRead', dict(after=self.data['cursor'], limit=500))
        with self.lock:
            known = {item['id'] for item in self.data['inputs']}
            for message in batch['items']:
                if (message['direction'] not in ('inbound', 'incoming')
                        or message.get('messageType') not in ('text', 'post')
                        or not message.get('text', '').strip() or message['messageId'] in known):
                    continue
                channel = self._channel(message)
                if self.data['channel'] is None:
                    self.data['channel'] = channel
                same = self._same_channel(channel, self.data['channel'])
                if same:
                    self.data['channel'] = channel
                self.data['inputs'].append(dict(id=message['messageId'], channel=channel, text=message['text'],
                    state='queued' if same else 'failed',
                    error='' if same else '此应用已连接另一个飞书会话；此消息未交给 Codex。'))
                known.add(message['messageId'])
            self.data['cursor'] = batch['nextCursor']
            self._save()

    def _enqueue_output(self, key, source, text, channel=None):
        # Caller holds the lock; acceptance means the output is durably owned.
        existing = next((row for row in self.data['outputs'] if row['id'] == key), None)
        if existing is not None:
            if existing['text'] != text:
                raise ValueError('同一输出标识对应了不同正文')
            return
        self.data['outputs'].append(dict(id=key, source=source, text=text, channel=deepcopy(channel), state='queued', error=''))

    def _poll_codex(self):
        self.codex = self.context.call('codexGet', {})
        terminal = [turn for turn in self.codex['turns'] if turn['status'] in ('completed', 'failed', 'interrupted', 'stopped')]
        with self.lock:
            if self.data['seenCodex'] is None:
                self.data['seenCodex'] = [turn['turnId'] for turn in terminal]
            else:
                seen = set(self.data['seenCodex'])
                for turn in terminal:
                    if turn['turnId'] in seen:
                        continue
                    route = next((item['channel'] for item in reversed(self.data['inputs'])
                                  if item.get('turnId') == turn['turnId']), self.data['channel'])
                    text = turn.get('reply')
                    if turn['status'] != 'completed':
                        error = turn.get('error')
                        detail = error.get('message', '') if isinstance(error, dict) else str(error or '')
                        text = 'Codex 本轮' + ('失败' if turn['status'] == 'failed' else '已停止') + ('：' + detail if detail else '')
                    if text:
                        self._enqueue_output('codex:' + turn['turnId'], 'codex', text, route)
                    self.data['seenCodex'].append(turn['turnId'])
                    seen.add(turn['turnId'])
            self._save()

    def _set(self, item, **values):
        with self.lock:
            item.update(values)
            self._save()

    def _submit(self):
        with self.lock:
            item = next((row for row in self.data['inputs'] if row['state'] not in ('submitted', 'skipped')
                         and self._same_channel(row['channel'], self.data['channel'])), None)
        if item is None or item['state'] != 'queued' or self.codex.get('connection') != 'ready' or self._stopped():
            return
        self._set(item, state='sending', error='')
        try:
            result = self.context.call('codexSend', dict(text=item['text'], mode='steer' if self.codex['activeTurnId'] else 'start'))
            self._set(item, state='submitted', threadId=result['threadId'], turnId=result.get('turnId'))
        except Exception as error:
            self._set(item, state='failed' if rejected(error) else 'unknown', error=str(error))

    def _flush(self):
        with self.lock:
            item = next((row for row in self.data['outputs'] if row['state'] == 'queued'), None)
            if item is None or self._stopped():
                return
            if item['channel'] is None:
                if self.data['channel'] is None:
                    return
                item['channel'] = deepcopy(self.data['channel'])
                self._save()
        self._set(item, state='sending', error='')
        try:
            result = self.context.call('feishuReply', dict(message_id=item['channel']['messageId'], text=item['text'],
                                                        reply_in_thread=bool(item['channel']['threadId'])))
            self._set(item, state='sent', messageId=result['messageId'])
        except Exception as error:
            self._set(item, state='failed' if rejected(error) else 'unknown', error=str(error))

    def _step(self, phase, action):
        if phase in self.paused or self._stopped():
            return
        try:
            action()
            self.issues.pop(phase, None)
        except Exception as error:
            self.issues[phase] = str(error)
            self.paused.add(phase)

    def _loop(self):
        while not self._stopped():
            self._step('codex', self._poll_codex)
            self._step('receive', self._receive)
            if 'codex' not in self.paused:
                self._step('submit', self._submit)
            self._step('output', self._flush)
            self._publish()
            self.wake.wait(self.interval)
            self.wake.clear()

    def _bridge_output(self, params):
        result = params.get('result')
        if (not isinstance(result, dict)
                or any(not isinstance(result.get(key), str) or not result[key] for key in ('deliveryId', 'sessionId', 'runId', 'status'))
                or result['status'] not in ('completed', 'failed', 'stopped')
                or result.get('reply') is not None and not isinstance(result['reply'], str)
                or 'replyTruncated' in result and type(result['replyTruncated']) is not bool):
            raise ValueError('Bridge 回调需要有效的 deliveryId、sessionId、runId、status 和 reply')
        text = result.get('reply') or 'Bridge 任务已完成，无文字输出。'
        if result['status'] != 'completed':
            text = 'Bridge 任务' + ('失败' if result['status'] == 'failed' else '已停止') + ('：\n' + result['reply'] if result.get('reply') else '')
        if result.get('replyTruncated'):
            text += '\n（Bridge 标记此结果已截短）'
        with self.lock:
            self._enqueue_output('bridge:' + result['deliveryId'] + ':' + result['runId'], 'bridge', text, self.data['channel'])
            self._save()
        self.wake.set()
        self._publish()
        return dict(accepted=True)

    def handle(self, command, params):
        if command == 'bridge_output':
            return self._bridge_output(params)
        if command == 'continue':
            self.paused.clear()
            self.issues.clear()
            self.wake.set()
            return dict(success=True)
        kind = params['kind']
        with self.lock:
            if kind == 'legacy':
                item = next(row for row in self.data['legacy']['tasks'] if row['id'] == params['id'])
                if item.get('migratedTo') or item['state'] in ('done', 'skipped'):
                    raise ValueError('此旧任务已经处理')
                if command == 'skip':
                    item['state'] = 'skipped'
                elif command == 'transfer' and item['state'] not in ('unknown', 'sending'):
                    channel = dict(chatId=item['chatId'], threadId=item['threadId'], messageId=item['messageId'])
                    if self.data['channel'] is None:
                        self.data['channel'] = channel
                    elif not self._same_channel(channel, self.data['channel']):
                        raise ValueError('旧任务不属于当前连接的飞书会话')
                    identity = uuid4().hex
                    self.data['inputs'].append(dict(id=identity, channel=channel, text=item['text'], state='queued', error=''))
                    item['migratedTo'] = identity
                else:
                    raise ValueError('旧发送结果未知，请先核对，不能自动重新处理')
            elif kind in ('inputs', 'outputs'):
                item = next(row for row in self.data[kind] if row['id'] == params['id'])
                if command == 'retry' and item['state'] in ('failed', 'unknown'):
                    if kind == 'inputs' and not self._same_channel(item['channel'], self.data['channel']):
                        raise ValueError('此消息不属于当前连接的飞书会话')
                    item.update(state='queued', error='')
                elif command == 'confirm' and item['state'] == 'unknown':
                    item.update(state='submitted' if kind == 'inputs' else 'sent', error='')
                elif command == 'skip' and item['state'] in ('failed', 'unknown'):
                    item['state'] = 'skipped'
                else:
                    raise ValueError('此项当前不支持所选操作')
            else:
                raise ValueError('未知队列')
            self._save()
        self.wake.set()
        self._publish()
        return dict(success=True)


def create(context):
    return Service(context)
