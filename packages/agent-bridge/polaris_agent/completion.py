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

    def prepare(self, delivery_id, address, ctx, interaction=None):
        addresses = [value for value in (address, interaction) if value is not None]
        if not addresses: return None
        for value in addresses:
            if (not isinstance(value, dict) or set(value) != {'target','operation','params'}
                    or any(not isinstance(value[k], str) or not value[k] or len(value[k]) > 256 for k in ('target','operation'))
                    or not isinstance(value['params'], dict) or 'result' in value['params']):
                raise ValueError('invalid completion callback')
        if ctx is None: raise ValueError('completion callback requires request authority')
        ctx.remember_task(self.task(delivery_id), [(v['target'],v['operation']) for v in addresses])
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
            # The token-free feed is a rebuildable projection of the durable journal.
            # Retry a failed export even if no further host events arrive.
            with self.store.lock:
                if self.store.notification_export_pending:
                    try: self.store.export_notifications()
                    except OSError: pass
            self._flush_requests()
            self._flush()

    def _flush_requests(self):
        bridge = self.component.bridge
        if bridge is None: return
        with self.store.lock:
            bridge.interactions.expire()
            pending = copy.deepcopy([r for r in self.store.requests.values()
                if r['state']=='pending' and r.get('notificationStatus') in ('waiting','blocked')])
            deliveries = copy.deepcopy(list(self.store.deliveries.values()))
        for request in pending:
            delivery = next((d for d in reversed(deliveries) if d.get('status')=='accepted'
                and d.get('sessionId')==request['sessionId'] and d.get('runId')==request['runId'] and d.get('onInteraction')),None)
            if delivery is None: continue
            address = delivery['onInteraction']
            try:
                context = self.component.resume_task(self.task(delivery['id']))
                if context is None: continue
                payload = {k:request[k] for k in ('id','sessionId','runId','kind','prompt','options','expiresAt','responseToken')}
                payload.update(deliveryId=delivery['id'])
                with self.store.transaction():
                    current = self.store.requests[request['id']]
                    if current['state'] != 'pending': continue
                    current.update(notificationStatus='sending',responseSource=address['target'])
                    self.store.changed()
                result = context.call(address['target'],address['operation'],{**address['params'],'result':payload})
                status = 'delivered' if isinstance(result,dict) and result.get('accepted') is True else 'unknown'
            except PlatformError as error:
                status = 'blocked' if error.code in ('interaction_not_ready','unavailable','stale_handle','component_unavailable','permission_required','stale_instance') else 'unknown'
            except Exception:
                status = 'unknown'
            with self.store.transaction():
                self.store.requests[request['id']]['notificationStatus'] = status
                self.store.changed()

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
