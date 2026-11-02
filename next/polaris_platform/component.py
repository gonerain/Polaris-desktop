"""Small optional helper; duck-typed implementations are supported."""
from copy import deepcopy
from threading import RLock
from .protocol import PlatformError, validate_description, _dispatched, handler_signature


class Component:
    def __init__(self):
        self._handlers = {}
        self._operations = {}
        self.events = {}
        self.views = []
        self.dependencies = []
        self.port = None
        self._registration = RLock()

    def _register(self, group, name, metadata, handler=None):
        with self._registration:
            entries = self._operations if group == 'operations' else self.events
            candidate = dict(entries)
            if metadata is None:
                candidate.pop(name, None)
            else:
                candidate[name] = deepcopy(metadata)
            validate_description({group: candidate})
            previous_handler = self._handlers.get(name)
            if group == 'operations':
                self._operations = candidate
                if handler is None:
                    self._handlers.pop(name, None)
                else:
                    self._handlers[name] = handler
            else:
                self.events = candidate
            try:
                if self.port is not None:
                    self.port.advertise()
            except Exception:
                if group == 'operations':
                    self._operations = entries
                    if previous_handler is None:
                        self._handlers.pop(name, None)
                    else:
                        self._handlers[name] = previous_handler
                else:
                    self.events = entries
                raise

    def operation(self, name, access="read", major=1, revision=1, interface=None, *, provides=None, requires=None):
        def register(handler):
            meta = dict(access=access, major=major, revision=revision, interface=interface)
            if provides is not None:
                meta['provides'] = provides
            if requires is not None:
                meta['requires'] = requires
            self._register('operations', name, meta, handler)
            return handler
        return register

    def withdraw_operation(self, name):
        self._register('operations', name, None)

    def event(self, name, access='read', major=1, revision=1, *, provides=None, requires=None):
        meta = dict(access=access, major=major, revision=revision)
        if provides is not None:
            meta['provides'] = provides
        if requires is not None:
            meta['requires'] = requires
        self._register('events', name, meta)

    def withdraw_event(self, name):
        self._register('events', name, None)

    def describe(self):
        return dict(operations=dict(self._operations), events=dict(self.events),
                    views=list(self.views), dependencies=list(self.dependencies))

    def start(self, port):
        self.port = port

    def stop(self):
        self.port = None

    def call(self, operation, params, context):
        with self._registration:
            handler = self._handlers.get(operation)
            if handler is None:
                raise PlatformError("missing_operation", operation)
            expected = _dispatched.get()
            if expected is not None and handler_signature(self._operations[operation]) != expected:
                raise PlatformError('stale_handle', operation)
        return handler(params, context)
