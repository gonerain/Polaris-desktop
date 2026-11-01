"""Optional result callbacks. No transport or recipient component dependency."""
import copy
import hashlib
import threading
from polaris_platform.protocol import PlatformError


class Completions:
    def __init__(self, component):
        self.component = component
        self.store = component.store
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.dispatch_lock = threading.Lock()
        self.store.listeners.append(self.wake.set)
        self.thread = threading.Thread(target=self.run, daemon=True, name='agent-completions')

    @staticmethod
    def task(delivery_id):
        return 'completion-' + hashlib.sha256(delivery_id.encode()).hexdigest()[:48]

    def prepare(self, delivery_id, address, ctx):
        if address is None:
            return None
        if (not isinstance(address, dict) or set(address) != {'target','operation','params'}
                or any(not isinstance(address[k], str) or not address[k] or len(address[k]) > 256 for k in ('target','operation'))
                or not isinstance(address['params'], dict) or 'result' in address['params']):
            raise ValueError('invalid completion callback')
        if ctx is None:
            raise ValueError('completion callback requires request authority')
        ctx.remember_task(self.task(delivery_id), [(address['target'], address['operation'])])
        return copy.deepcopy(address)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.wake.set()
        self.thread.join(2)
        self.store.listeners.remove(self.wake.set)

    def run(self):
        while not self.stopped.is_set():
            self.wake.wait(2)
            self.wake.clear()
            if self.stopped.is_set():
                return
            try:
                self.flush()
            except (ValueError, OSError):
                # A failed state save must never cause an unrecorded dispatch.
                continue
            finally:
                # Own progress writes also signal the store. Do not spin on a
                # blocked receiver; a concurrent new event is checked in <=2s.
                self.wake.clear()

    def flush(self):
        with self.dispatch_lock:
            self._flush()

    def _flush(self):
        with self.store.lock:
            deliveries = copy.deepcopy(list(self.store.deliveries.values()))
        for delivery in deliveries:
            if self.stopped.is_set():
                return
            address = delivery.get('onComplete')
            if not address or delivery.get('status') != 'accepted' or delivery.get('completionStatus', 'waiting') not in ('waiting','blocked'):
                continue
            row = self.store.status(delivery['sessionId'])
            run = next((r for r in row['runs'] if r['id'] == delivery.get('runId')), None)
            if run is None or run['status'] not in ('completed','failed','stopped'):
                continue
            context = None
            try:
                context = self.component.resume_task(self.task(delivery['id']))
                if context is None:
                    continue
                payload = dict(deliveryId=delivery['id'], sessionId=row['id'], runId=run['id'],
                               title=row['title'], status=run['status'], reply=run.get('reply'),
                               replyTruncated=run.get('replyTruncated',False))
                # Persist before calling. A crash in transit is uncertain, not a retry.
                self.update(delivery['id'], 'sending')
                answer = context.call(address['target'], address['operation'], {**address['params'], 'result':payload})
                if not isinstance(answer,dict) or answer.get('accepted') is not True:
                    self.update(delivery['id'], 'unknown')
                else:
                    self.update(delivery['id'], 'delivered')
                    context.forget_task(self.task(delivery['id']))
            except PlatformError as error:
                # These errors explicitly mean the callback did not dispatch.
                retryable = error.code in ('unavailable','stale_handle','component_unavailable','permission_required',
                                           'completion_not_ready','stale_instance')
                self.update(delivery['id'], 'blocked' if retryable else 'unknown', error.code)
            except Exception:
                self.update(delivery['id'], 'unknown', 'callback_outcome_unknown')

    def update(self, identity, status, detail=''):
        with self.store.transaction():
            row = self.store.deliveries[identity]
            if row.get('completionStatus') == status and row.get('completionDetail','') == detail:
                return
            row.update(completionStatus=status, completionDetail=detail)
            self.store.changed()
