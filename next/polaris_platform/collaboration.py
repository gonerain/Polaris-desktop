"""Directory and routing; handlers always execute outside directory locks."""
from copy import deepcopy
from collections import deque
from threading import RLock
from .component import Component
from .protocol import Handle, PlatformError, capability


class Collaboration(Component):
    def __init__(self):
        super().__init__()
        self._lock = RLock()
        self._entries = {}
        self._revision = 0
        self._changes = deque(maxlen=1024)
        self._subscriptions = {}
        self._running = False
        self.runtime = None
        self.operation("discover")(lambda p, c: self.discover())
        self.operation("watch")(lambda p, c: self.watch(p.get("after", 0)))
        self.operation("describe")(lambda p, c: self.describe_target(p["target"]))

    def start(self, port):
        super().start(port)
        self._running = True

    def stop(self):
        self._running = False
        with self._lock:
            self._subscriptions.clear()
        super().stop()

    def require_running(self):
        if not self._running:
            raise PlatformError("unavailable", "Collaboration is stopped")

    def advertise(self, record):
        with self._lock:
            self._entries[record["id"]] = deepcopy(record)
            self._changed(record["id"], "advertise")

    def withdraw(self, component_id):
        with self._lock:
            self._entries.pop(component_id, None)
            self._subscriptions = {k: v for k, v in self._subscriptions.items()
                                   if v[0] != component_id and v[2].caller != component_id}
            self._changed(component_id, "withdraw")

    def _changed(self, component_id, kind):
        self._revision += 1
        self._changes.append(dict(revision=self._revision, component=component_id, kind=kind))

    def discover(self):
        self.require_running()
        with self._lock:
            return dict(revision=self._revision, components=deepcopy(list(self._entries.values())))

    def describe_target(self, target):
        self.require_running()
        with self._lock:
            if target not in self._entries:
                raise PlatformError("unavailable", target)
            return deepcopy(self._entries[target])

    def watch(self, after=0):
        self.require_running()
        with self._lock:
            return dict(revision=self._revision, resync=bool(self._changes and after < self._changes[0]["revision"] - 1), changes=deepcopy([x for x in self._changes if x["revision"] > after]))

    def bind(self, target, operation):
        record = self.describe_target(target)
        metadata = record["description"].get("operations", {}).get(operation)
        if metadata is None:
            raise PlatformError("missing_operation", operation)
        if not metadata.get("available", True):
            raise PlatformError("dependency_unavailable", operation, metadata.get("reason"))
        return Handle(target, record["instance"], operation,
                      capability(record["installation"], "operation", operation, metadata))

    def invoke(self, handle, params, context):
        self.require_running()
        fresh = self.bind(handle.target, handle.operation)
        if fresh != handle:
            raise PlatformError("stale_handle", "Rebind to the current instance or capability")
        self.runtime.authorization.check(context, fresh.semantic)
        return self.runtime.dispatch(handle, params, context)

    def subscribe(self, target, event, callback, context):
        record = self.describe_target(target)
        meta = record["description"].get("events", {}).get(event)
        if meta is None or not meta.get("available", True):
            raise PlatformError("unavailable", event)
        key = capability(record["installation"], "event", event, meta)
        self.runtime.authorization.check(context, key)
        from uuid import uuid4
        token = uuid4().hex
        with self._lock:
            self._subscriptions[token] = (target, event, context, callback, record["instance"], key)
        return token

    def unsubscribe(self, token, caller):
        with self._lock:
            item = self._subscriptions.get(token)
            if item and item[2].caller == caller:
                self._subscriptions.pop(token)

    def publish(self, target, event, payload, publisher_context):
        record = self.describe_target(target)
        meta = record["description"].get("events", {}).get(event)
        if meta is None or not meta.get("available", True):
            raise PlatformError("unavailable", event)
        with self._lock:
            subscribers = list(self._subscriptions.items())
        results = []
        for token, (owner, name, context, callback, instance, key) in subscribers:
            if (owner, name) != (target, event):
                continue
            try:
                with self._lock:
                    if token not in self._subscriptions:
                        continue
                live = self.describe_target(target)
                live_metadata = live["description"].get("events", {}).get(event)
                if live_metadata is None or not live_metadata.get("available", True):
                    raise PlatformError("unavailable", event)
                live_key = capability(live["installation"], "event", event, live_metadata)
                if instance != live["instance"] or key != live_key:
                    raise PlatformError("stale_handle", "Subscription capability changed")
                self.runtime.authorization.check(context, key)
                # Event-triggered work retains publisher scope, intersected with subscriber scope.
                delivery = self.runtime.derive_event_context(context, publisher_context)
                self.runtime.deliver(context.caller, callback, payload, delivery)
                results.append(dict(subscription=token, delivered=True))
            except PlatformError as error:
                results.append(dict(subscription=token, delivered=False, error=error.as_dict()))
            except Exception as error:
                results.append(dict(subscription=token, delivered=False, error=PlatformError("component_error", str(error)).as_dict()))
        return results
