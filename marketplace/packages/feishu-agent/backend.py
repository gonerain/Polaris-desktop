"""Durable Feishu channel for one existing Codex CLI session and Bridge outputs."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from .panels import COMMANDS, panel_state, render_panel
from . import reminders


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
    card_interval = 0.15

    def __init__(self, context):
        self.context = context
        self.path = Path(context.data_directory) / 'state.json'
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.card_wake = threading.Event()
        self.thread = None
        self.card_thread = None
        self.running = False
        self.codex = {}
        self.issues = {}
        self.paused = set()
        self.card_action = None
        self.data = dict(schemaVersion=2, cursor=None, channel=None, inputs=[], outputs=[], seenCodex=None, legacy=None)
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if 'schemaVersion' not in saved:
                self.data.update(cursor=saved['cursor'], legacy=saved)
            elif saved['schemaVersion'] == 2:
                self.data = saved
            else:
                raise ValueError('不支持的飞书 Agent 数据版本')
        self.data.setdefault('actionCursor', 0)
        self.data.setdefault('panels', {})
        self.data.setdefault('reminders', reminders.initial_state())
        for queue in ('inputs', 'outputs'):
            for item in self.data[queue]:
                if item['state'] == 'sending':
                    item.update(state='unknown', error='上次投递未返回结果，请核对后再决定是否重发。')
        for output in self.data['outputs']:
            if output['source'] == 'reminder' and output['state'] == 'unknown':
                plan = next(row for row in self.data['reminders']['plans'] if row['id'] == output['reminderId'])
                plan['state'] = 'unknown'
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
                    planning = item.get('source') == 'reminder-plan'
                    rows.append(dict(id=item['id'], kind=kind, state=item['state'],
                                     text='内部提醒规划请求未完成' if planning else item['text'],
                                     error=item['error'] + ('。核对后跳过旧规划，使用最新增量重新规划。' if planning else '')))
        if self.card_action is not None and 'cards' in self.paused:
            rows.append(dict(id=str(self.card_action['cursor']), kind='cards', state='failed',
                             text='飞书卡片操作未完成', error=self.issues['cards']))
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
                reminders=reminders.summary(self.data['reminders']),
                callback=dict(target=self.context.application_id, operation='bridge_output', params={})))

    def _stopped(self):
        return not self.running or self.context.stopped.is_set()

    def start(self):
        self.running = True
        self._publish()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.card_thread = threading.Thread(target=self._card_loop, daemon=True)
        self.thread.start()
        self.card_thread.start()

    def stop(self):
        self.running = False
        self.wake.set()
        self.card_wake.set()
        if self.thread is not None:
            self.thread.join()
        if self.card_thread is not None:
            self.card_thread.join()
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
                panel_view = COMMANDS.get(message['text'].strip()) if same else None
                self.data['inputs'].append(dict(id=message['messageId'], channel=channel, text=message['text'],
                    state='handled' if panel_view else 'queued' if same else 'failed',
                    error='' if same else '此应用已连接另一个飞书会话；此消息未交给 Codex。'))
                if panel_view:
                    self._enqueue_panel('panel:' + message['messageId'], panel_view, channel)
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

    def _enqueue_panel(self, key, view, channel):
        self._enqueue_output(key, 'panel', '标记会话卡片' if view == 'sessions' else '日程任务卡片', channel)
        row = next(row for row in self.data['outputs'] if row['id'] == key)
        row['panel'] = panel_state(view)

    def _render_panel(self, state):
        result = None
        if state['view'] == 'sessions':
            data = self.context.call('bridgeSessions', dict(marked=True))
            if state['detailId'] is not None and any(row['id'] == state['detailId'] for row in data):
                result = self.context.call('bridgeResult', dict(session_id=state['detailId'], completed_only=True))
        else:
            data = self.context.call('scheduleGet', {})
        return render_panel(self.context.application_id, state, data, result)

    def _receive_actions(self):
        if self.data['channel'] is None:
            return
        self.card_action = None
        batch = self.context.call('feishuActions', dict(after=self.data['actionCursor'], limit=100))
        for event in batch['items']:
            with self.lock:
                known = deepcopy(self.data['panels'].get(event['messageId']))
            action = event['action']
            value = action.get('value')
            if (known is not None and event['chatId'] == known['channel']['chatId']
                    and isinstance(value, dict) and value.get('app') == self.context.application_id):
                self.card_action = event
                state = panel_state(value['view'], filter=value['filter'], page=value['page'], detailId=value['detailId'])
                card, state = self._render_panel(state)
                self.context.call('feishuUpdateCard', dict(message_id=event['messageId'], card=card))
                with self.lock:
                    self.data['panels'][event['messageId']] = dict(state, channel=known['channel'])
                self.card_action = None
            with self.lock:
                self.data['actionCursor'] = event['cursor']
                self._save()
        return bool(batch['items'])

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
                    if any(item.get('source') == 'reminder-plan' and
                           (item.get('turnId') == turn['turnId'] or turn.get('message') == item['text'])
                           for item in self.data['inputs']):
                        self.data['seenCodex'].append(turn['turnId'])
                        seen.add(turn['turnId'])
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
            active = self.data['reminders']['activeInput']
            if active is not None:
                planning = next(row for row in self.data['inputs'] if row['id'] == active)
                if planning['state'] == 'submitted' and not planning.get('planFinished'):
                    return  # Never steer a chat message into an internal planning turn.
            item = next((row for row in self.data['inputs'] if row['state'] not in ('submitted', 'skipped', 'handled')
                         and self._same_channel(row['channel'], self.data['channel'])), None)
        if item is None or item['state'] != 'queued' or self.codex.get('connection') != 'ready' or self._stopped():
            return
        if item.get('source') == 'reminder-plan' and self.codex['activeTurnId']:
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
        if item['source'] == 'reminder':
            try:
                with self.lock:
                    plan = next(row for row in self.data['reminders']['plans'] if row['id'] == item['reminderId'])
                    if not self.data['reminders']['enabled'] or plan['state'] != 'queued':
                        self._set(item, state='skipped', error=plan['reason'] or '提醒已关闭')
                        return
                self._observe_reminders()
                with self.lock:
                    if not self.data['reminders']['enabled'] or plan['state'] != 'queued':
                        self._set(item, state='skipped', error=plan['reason'] or '提醒已关闭')
                        return
            except Exception as error:
                with self.lock:
                    plan.update(state='failed', reason=str(error))
                    self._set(item, state='failed', error=str(error))
                return
        if 'panel' in item:
            try:
                card, state = self._render_panel(item['panel'])
            except Exception as error:
                self._set(item, state='failed', error=str(error))
                return
            content = dict(message={'card': card})
        else:
            content = dict(text=item['text'])
        self._set(item, state='sending', error='')
        try:
            result = self.context.call('feishuReply', dict(message_id=item['channel']['messageId'],
                reply_in_thread=bool(item['channel']['threadId']), **content))
            with self.lock:
                if 'panel' in item:
                    self.data['panels'][result['messageId']] = dict(state, channel=deepcopy(item['channel']))
                if item['source'] == 'reminder':
                    plan.update(state='sent', sentAt=self._now().isoformat(), reason='')
                self._set(item, state='sent', messageId=result['messageId'])
        except Exception as error:
            with self.lock:
                if item['source'] == 'reminder':
                    plan.update(state='failed' if rejected(error) else 'unknown', reason=str(error))
                self._set(item, state='failed' if rejected(error) else 'unknown', error=str(error))

    def _now(self):
        return datetime.now().astimezone()

    def _observe_reminders(self):
        snapshot = self.context.call('scheduleGet', {})
        now = self._now()
        with self.lock:
            before = deepcopy(self.data['reminders'])
            reminders.reconcile(self.data['reminders'], snapshot, now)
            # Invalidate queued/failed outputs too; unknown sends require human reconciliation.
            plans = {row['id']: row for row in self.data['reminders']['plans']}
            outputs_changed = False
            for output in self.data['outputs']:
                if output['source'] == 'reminder' and output['state'] in ('queued', 'failed'):
                    plan = plans[output['reminderId']]
                    if plan['state'] in ('cancelled', 'expired'):
                        output.update(state='skipped', error=plan['reason'])
                        outputs_changed = True
            if outputs_changed or before != self.data['reminders']:
                self._save()
        return now

    def _remind(self):
        state = self.data['reminders']
        if not state['enabled'] and state['activeInput'] is None:
            return
        now = self._observe_reminders() if state['enabled'] else self._now()
        with self.lock:
            active = state['activeInput']
            if active is not None:
                item = next(row for row in self.data['inputs'] if row['id'] == active)
                if item['state'] == 'skipped':
                    state['activeInput'] = None
                elif item['state'] == 'submitted' and not item.get('planFinished'):
                    turn = next((row for row in self.codex['turns'] if row['turnId'] == item['turnId']), None)
                    if turn is not None and turn['status'] != 'running':
                        if turn['status'] != 'completed':
                            item['planFinished'] = True
                            state['activeInput'] = None
                            self._save()
                            raise ValueError('提醒规划回合未完成：' + turn['status'])
                        try:
                            reminders.accept(state, item['planningBatch'], turn['reply'], now)
                        except Exception:
                            item['planFinished'] = True
                            state['activeInput'] = None
                            self._save()
                            raise
                        item['planFinished'] = True
                        state['activeInput'] = None
                        self._save()
            if not state['enabled']:
                return
            for plan in state['plans']:
                if plan['state'] == 'scheduled' and reminders.instant(plan['sendAt']) <= now:
                    self._enqueue_output('reminder:' + plan['id'], 'reminder', plan['text'], self.data['channel'])
                    self.data['outputs'][-1]['reminderId'] = plan['id']
                    plan['state'] = 'queued'
                    self._save()
            if (state['activeInput'] is not None or self.data['channel'] is None or
                    state['nextCheck'] is not None and reminders.instant(state['nextCheck']) > now):
                return
            if state['pending'] and (self.codex.get('connection') != 'ready' or self.codex.get('activeTurnId') or
                    any(row['state'] == 'queued' for row in self.data['inputs'])):
                return  # Wait for the current conversation, rather than steering it.
            state['lastCheck'] = now.isoformat()
            state['nextCheck'] = (now + timedelta(hours=1)).isoformat()
            if state['pending']:
                request = reminders.batch(state)
                identity = uuid4().hex
                self.data['inputs'].append(dict(id=identity, source='reminder-plan', planningBatch=request,
                    channel=deepcopy(self.data['channel']), text=reminders.prompt(request, now), state='queued', error=''))
                state['activeInput'] = identity
            self._save()

    def _step(self, phase, action):
        with self.lock:
            if phase in self.paused or self._stopped():
                return
        try:
            result = action()
            with self.lock:
                self.issues.pop(phase, None)
            return result
        except Exception as error:
            with self.lock:
                self.issues[phase] = str(error)
                self.paused.add(phase)

    def _card_loop(self):
        while not self._stopped():
            previous_error = self.issues.get('cards')
            changed = self._step('cards', self._receive_actions)
            if changed or self.issues.get('cards') != previous_error:
                self._publish()
            self.card_wake.wait(self.card_interval)
            self.card_wake.clear()

    def _loop(self):
        while not self._stopped():
            self._step('codex', self._poll_codex)
            self._step('receive', self._receive)
            self._step('reminders', self._remind)
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
        if command == 'configure_reminders':
            with self.lock:
                reminders.configure(self.data['reminders'], params['enabled'], params['preferences'])
                # Disabling also prevents an unsent internal request from running later.
                active = self.data['reminders']['activeInput']
                if active is not None:
                    item = next(row for row in self.data['inputs'] if row['id'] == active)
                    if item['state'] == 'queued':
                        item['state'] = 'skipped'
                        self.data['reminders']['activeInput'] = None
                self._save()
            self.wake.set()
            self._publish()
            return dict(success=True)
        if command == 'bridge_output':
            return self._bridge_output(params)
        if command in ('show_sessions', 'show_schedule'):
            with self.lock:
                if self.data['channel'] is None:
                    raise ValueError('请先在飞书发送一条新消息建立连接')
                self._enqueue_panel(uuid4().hex, 'sessions' if command == 'show_sessions' else 'schedule', self.data['channel'])
                self._save()
            self.wake.set()
            self._publish()
            return dict(success=True)
        if command == 'continue':
            with self.lock:
                if 'reminders' in self.paused:
                    self.data['reminders']['nextCheck'] = None
                self.paused.clear()
                self.issues.clear()
            self.wake.set()
            self.card_wake.set()
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
            elif kind == 'cards':
                if self.card_action is None or str(self.card_action['cursor']) != params['id'] or command not in ('retry', 'skip'):
                    raise ValueError('此卡片操作已处理或不支持所选操作')
                if command == 'skip':
                    self.data['actionCursor'] = self.card_action['cursor']
                    self.card_action = None
                self.paused.discard('cards')
                self.issues.pop('cards', None)
            elif kind in ('inputs', 'outputs'):
                item = next(row for row in self.data[kind] if row['id'] == params['id'])
                if command == 'retry' and item['state'] in ('failed', 'unknown'):
                    if item.get('source') == 'reminder-plan':
                        raise ValueError('请跳过旧规划并点击「继续」，使用最新增量重新规划')
                    if kind == 'outputs' and item['source'] == 'reminder':
                        plan = next(row for row in self.data['reminders']['plans'] if row['id'] == item['reminderId'])
                        if plan['state'] in ('cancelled', 'expired') or not self.data['reminders']['enabled']:
                            raise ValueError('提醒已失效，不能重发')
                        plan.update(state='queued', reason='')
                    if kind == 'inputs' and not self._same_channel(item['channel'], self.data['channel']):
                        raise ValueError('此消息不属于当前连接的飞书会话')
                    item.update(state='queued', error='')
                elif command == 'confirm' and item['state'] == 'unknown':
                    if item.get('source') == 'reminder-plan' and not item.get('turnId'):
                        turn = next((row for row in self.codex['turns'] if row.get('message') == item['text']), None)
                        if turn is None:
                            raise ValueError('尚未找到对应的 Codex 规划回合；请核对后跳过旧规划')
                        item.update(turnId=turn['turnId'], threadId=turn['threadId'])
                    if kind == 'outputs' and item['source'] == 'reminder':
                        plan = next(row for row in self.data['reminders']['plans'] if row['id'] == item['reminderId'])
                        plan.update(state='sent', sentAt=self._now().isoformat())
                    item.update(state='submitted' if kind == 'inputs' else 'sent', error='')
                elif command == 'skip' and item['state'] in ('failed', 'unknown'):
                    item['state'] = 'skipped'
                    if kind == 'outputs' and item['source'] == 'reminder':
                        plan = next(row for row in self.data['reminders']['plans'] if row['id'] == item['reminderId'])
                        plan.update(state='skipped', reason='用户跳过')
                    if item.get('source') == 'reminder-plan':
                        self.data['reminders']['activeInput'] = None
                        self.data['reminders']['nextCheck'] = None
                else:
                    raise ValueError('此项当前不支持所选操作')
            else:
                raise ValueError('未知队列')
            self._save()
        self.wake.set()
        self.card_wake.set()
        self._publish()
        return dict(success=True)


def create(context):
    return Service(context)
