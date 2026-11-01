"""Small optional helper; duck-typed implementations are supported."""
from .protocol import PlatformError


class Component:
    def __init__(self):
        self._handlers = {}
        self._operations = {}
        self.events = {}
        self.views = []
        self.dependencies = []
        self.port = None

    def operation(self, name, access="read", major=1, revision=1, interface=None):
        def register(handler):
            self._handlers[name] = handler
            self._operations[name] = dict(access=access, major=major, revision=revision, interface=interface)
            return handler
        return register

    def withdraw_operation(self, name):
        self._operations.pop(name, None)
        self._handlers.pop(name, None)
        if self.port is not None:
            self.port.advertise()

    def withdraw_event(self, name):
        self.events.pop(name, None)
        if self.port is not None:
            self.port.advertise()

    def describe(self):
        return dict(operations=dict(self._operations), events=dict(self.events),
                    views=list(self.views), dependencies=list(self.dependencies))

    def start(self, port):
        self.port = port

    def stop(self):
        self.port = None

    def call(self, operation, params, context):
        if operation not in self._handlers:
            raise PlatformError("missing_operation", operation)
        return self._handlers[operation](params, context)
