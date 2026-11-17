"""Agent-owned sessions and run results. Transport presence is never completion."""
import hashlib
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid


def session_key(adapter, client_id, session_id):
    return hashlib.sha256(json.dumps([adapter, client_id, session_id]).encode()).hexdigest()


def text(value, name, limit=4096):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f'invalid {name}')
    return value


class AgentStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.listeners = []
        self.notices = []
        self.storage_notice = ''
        self.notification_export_pending = False
        self.rows = {}
        self.deliveries = {}
        self.requests = {}
        self.notifications = {"version": 1, "id": uuid.uuid4().hex, "events": []}
        migrate_notifications = False
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('sessions'), dict):
                raise ValueError('unsupported Agent data')
            self.rows = data['sessions']
            self.deliveries = data.get('deliveries', {})
            self.requests = data.get('requests', {})
            self.notifications = data.get('notifications', self.notifications)
            migrate_notifications = 'notifications' not in data
            projection = self.path.with_name('notifications.json')
            if migrate_notifications and projection.exists():
                # A previous component version may have removed the primary copy
                # while the consumer's established feed remains on disk.
                recovered = json.loads(projection.read_text(encoding='utf-8'))
                if (not isinstance(recovered, dict) or recovered.get('version') != 1 or
                        not isinstance(recovered.get('id'), str) or not recovered['id'] or
                        not isinstance(recovered.get('events'), list)):
                    raise ValueError('invalid existing notification feed')
                seen = set()
                for sequence, event in enumerate(recovered['events'], 1):
                    if (not isinstance(event, dict) or event.get('sequence') != sequence or
                            not isinstance(event.get('id'), str) or not event['id'] or event['id'] in seen):
                        raise ValueError('invalid existing notification feed')
                    seen.add(event['id'])
                self.notifications = recovered
        for request in self.requests.values():
            if request['state'] == 'pending': request.update(state='expired', responseToken='')
        for delivery in self.deliveries.values():
            if delivery.get('completionStatus') == 'sending':
                delivery['completionStatus'] = 'unknown'
            if delivery.get('status') == 'pending':
                delivery['status'] = 'unknown'
        for row in self.rows.values():
            row['online'] = False
            row['canSend'] = False

        if self.path.exists():
            if migrate_notifications:
                # Persist the new source identity before exposing it to consumers.
                self.save()
            else:
                try: self.export_notifications()
                except OSError: self.notification_export_pending = True

    @contextmanager
    def transaction(self):
        with self.lock:
            before = copy.deepcopy((self.rows, self.deliveries, self.notices, self.requests, self.notifications))
            try:
                yield
            except Exception:
                self.rows, self.deliveries, self.notices, self.requests, self.notifications = before
                raise

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({'version': 1, 'sessions': self.rows, 'deliveries': self.deliveries, 'requests': self.requests, 'notifications': self.notifications}, ensure_ascii=False).encode()
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as file:
                name = file.name
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
            # A separate, token-free projection for explicitly enabled local consumers.
            # Primary state is authoritative; failed exports are repaired on next save/start.
            try:
                self.export_notifications()
            except OSError:
                self.notification_export_pending = True
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def export_notifications(self):
        path = self.path.with_name('notifications.json')
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
                name = file.name
                file.write(json.dumps(self.notifications, ensure_ascii=False).encode())
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, path)
            self.notification_export_pending = False
        finally:
            if name and os.path.exists(name): os.unlink(name)

    def notify(self, row, event, identity, **fields):
        if row['adapter'].lower() != 'codex': return
        key = hashlib.sha256(json.dumps([row['id'], event, identity]).encode()).hexdigest()
        events = self.notifications['events']
        if any(e['id'] == key for e in events): return
        events.append(dict(id=key, sequence=len(events) + 1, event=event,
                           sessionId=row['id'], nativeSessionId=row['sessionId'],
                           adapter=row['adapter'], clientId=row['clientId'], title=row['title'],
                           createdAt=time.time(), **fields))

    def changed(self):
        try:
            self.save()
            self.storage_notice = ''
        except OSError as error:
            self.storage_notice = f'Agent 保存失败：{error}'
            raise ValueError(self.storage_notice) from error
        for callback in tuple(self.listeners):
            try:
                callback()
            except Exception:
                pass

    def snapshot(self, adapter, client_id, session_id, **fields):
        text(session_id, 'sessionId')
        key = session_key(adapter, client_id, session_id)
        with self.transaction():
            row = self.rows.setdefault(key, {'id': key, 'adapter': adapter, 'clientId': client_id,
                'sessionId': session_id, 'marked': False, 'runs': [], 'title': session_id})
            liveness = fields.get('liveness', 'host')
            if liveness not in ('host', 'connection', 'unverified'):
                raise ValueError('invalid liveness')
            row.update(online=True, liveness=liveness, canSend=bool(fields.get('canSend', False)) and liveness == 'host')
            for field in ('title', 'cwd'):
                if field in fields and isinstance(fields[field], str):
                    row[field] = fields[field][:4096]
            self.changed()
            return copy.deepcopy(row)

    def sessions(self):
        with self.lock:
            return json.loads(json.dumps(list(self.rows.values())))

    def require(self, session_id):
        if session_id not in self.rows:
            raise ValueError('unknown session')
        return self.rows[session_id]

    def mark(self, session_id, marked=True):
        with self.transaction():
            row = self.require(session_id)
            row['marked'] = bool(marked)
            if not marked:
                for request in self.requests.values():
                    if request['sessionId']==session_id and request['state']=='pending':
                        request.update(state='expired',responseToken='')
            self.changed()
            return copy.deepcopy(row)

    def offline(self, adapter, client_id):
        with self.transaction():
            for row in self.rows.values():
                if (row['adapter'], row['clientId']) == (adapter, client_id):
                    row.update(online=False, canSend=False)
            self.changed()

    def run_event(self, key, run_id, status=None, reply=None, detail='', reply_truncated=False, prompt=None, prompt_truncated=False):
        text(run_id, 'runId')
        if status not in (None, 'completed', 'failed', 'stopped', 'unknown'):
            raise ValueError('invalid run status')
        with self.transaction():
            row = self.require(key)
            run = next((r for r in row['runs'] if r['id'] == run_id), None)
            if run is None:
                run = {'id': run_id, 'status': 'running', 'reply': None, 'startedAt': time.time()}
                row['runs'].append(run)
                row['runs'] = row['runs'][-100:]
            if isinstance(prompt, str):
                run.update(prompt=prompt[:4000], promptTruncated=bool(prompt_truncated) or len(prompt) > 4000)
            previous_status = run['status']
            if status is not None and (previous_status == 'running' or
                    (previous_status in ('unknown', 'stopped') and status in ('completed', 'failed')) or
                    (previous_status == 'unknown' and status == 'unknown') or
                    (previous_status == status and status in ('completed','failed','stopped') and not run.get('reply') and isinstance(reply,str))):
                run.update(status=status, reply=reply if isinstance(reply, str) else None,
                           detail=str(detail)[:4096], replyTruncated=bool(reply_truncated),
                           endedAt=run.get('endedAt', time.time()) if previous_status == status else time.time())
                if status in ('completed', 'failed', 'stopped'):
                    self.notify(row, 'run.ended', [run_id, status], runId=run_id,
                                status=status, prompt=run.get('prompt'), promptTruncated=run.get('promptTruncated', False),
                                reply=run.get('reply'), replyTruncated=run.get('replyTruncated', False))
                if row['marked'] and previous_status == 'running':
                    self.notices.append((dict(row), dict(run)))
            self.changed()
            return copy.deepcopy(run)

    def status(self, session_id):
        with self.lock:
            return json.loads(json.dumps(self.require(session_id)))

    def result(self, session_id, run_id=None):
        with self.lock:
            runs = self.require(session_id)['runs']
            if run_id is None:
                return dict(runs[-1]) if runs else None
            return next((dict(r) for r in runs if r['id'] == run_id), None)

    def delivery(self, delivery_id):
        with self.lock:
            return copy.deepcopy(self.deliveries[delivery_id])
