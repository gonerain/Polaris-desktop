"""Bound, expiring human requests; answer tokens never enter model-facing APIs."""
import copy
import secrets
import time
import uuid
from .model import text


class Interactions:
    def __init__(self, store):
        self.store = store

    def open(self, session_id, owner, run_id, kind, prompt, options=None, timeout=110):
        if kind not in ('approval', 'question'): raise ValueError('invalid interaction kind')
        text(run_id, 'runId', 256)
        text(prompt, 'prompt', 6000)
        if type(timeout) not in (int, float) or not 1 <= timeout <= 300: raise ValueError('invalid interaction timeout')
        options = options or []
        if not isinstance(options, list) or len(options) > 10 or any(not isinstance(v, str) or not v or len(v) > 500 for v in options):
            raise ValueError('invalid interaction options')
        with self.store.transaction():
            row = self.store.require(session_id)
            if (not row['online'] or [row['adapter'], row['clientId']] != list(owner) or
                    not row['marked'] and row['adapter'].lower() != 'codex'):
                raise ValueError('session is not online or belongs to another owner')
            if not any(r['id']==run_id and r['status']=='running' for r in row['runs']):
                raise ValueError('interaction does not belong to an active run')
            self.expire()
            if sum(r['state'] == 'pending' for r in self.store.requests.values()) >= 32:
                raise ValueError('too many pending interactions')
            identity = uuid.uuid4().hex
            request = dict(id=identity, sessionId=session_id, owner=list(owner), runId=run_id,
                kind=kind, prompt=prompt, options=options, state='pending', createdAt=time.time(),
                expiresAt=time.time()+timeout, responseToken=secrets.token_urlsafe(32), notificationStatus='waiting')
            self.store.notify(row, 'interaction.opened', identity, requestId=identity,
                              runId=run_id, kind=kind, prompt=prompt, options=options,
                              expiresAt=request['expiresAt'], actionable=False)
            # Observation is independent of control. Unmarked sessions never gain
            # response credentials and must immediately keep their native UI flow.
            if not row['marked']:
                request.update(state='observed', responseToken='')
            self.store.requests[identity] = request
            # Retain recent outcomes for late hook polls, not an unlimited history.
            terminal = sorted((v for v in self.store.requests.values() if v['state'] != 'pending'), key=lambda r:r['createdAt'])
            for old in terminal[:-100]: self.store.requests.pop(old['id'], None)
            self.store.changed()
            return dict(id=identity, state=request['state'], expiresAt=request['expiresAt'],
                        notificationOnly=not row['marked'])

    def expire(self, session_id=None):
        changed = False
        for request in self.store.requests.values():
            if request['state'] == 'pending' and (time.time() >= request['expiresAt'] or session_id == request['sessionId']):
                request.update(state='expired', responseToken='')
                changed = True
        return changed

    def native_status(self, identity, owner, session_id, close=False):
        with self.store.transaction():
            r = self.store.requests.get(identity)
            if not r or r['owner'] != list(owner) or r['sessionId'] != session_id: raise ValueError('unknown interaction')
            changed = self.expire()
            if close and r['state'] == 'pending':
                r.update(state='expired',responseToken='')
                changed = True
            if changed: self.store.changed()
            return {key:copy.deepcopy(r[key]) for key in ('id','state','kind','answer') if key in r}

    def pending(self, session_id=None):
        with self.store.lock:
            self.expire()
            return [{k:copy.deepcopy(r[k]) for k in ('id','sessionId','runId','kind','prompt','options','state','expiresAt')}
                    for r in self.store.requests.values() if r['state']=='pending' and (session_id is None or r['sessionId']==session_id)
                    and self.store.require(r['sessionId'])['marked'] and self.store.require(r['sessionId'])['online']]

    def respond(self, request_id, response_token, answer, source):
        with self.store.lock:
            if self.expire(): self.store.changed()
            with self.store.transaction():
                r = self.store.requests.get(request_id)
                if (not r or r['state'] != 'pending' or not isinstance(response_token, str)
                        or not secrets.compare_digest(r['responseToken'], response_token)
                        or source != r.get('responseSource')):
                    raise ValueError('interaction is unavailable or response authority does not match')
                row = self.store.require(r['sessionId'])
                if not row['marked'] or not row['online']: raise ValueError('session is unavailable')
                if r['kind'] == 'approval' and answer not in ('allow', 'deny'): raise ValueError('approval requires allow or deny')
                text(answer, 'answer', 8000)
                r.update(state='answered',answer=answer,responseToken='')
                self.store.changed()
                return dict(accepted=True,requestId=request_id,state='answered')
