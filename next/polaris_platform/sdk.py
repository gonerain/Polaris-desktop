"""Small function-based SDK for in-process and stdio components."""
from __future__ import annotations
import inspect
import sys
import threading
from .component import Component as BaseComponent
from .protocol import PlatformError, _dispatched
from .transport import _Peer


class Component(BaseComponent):
    """Register plain keyword handlers; optional ``ctx`` carries request authority."""
    def operation(self, name, access='read', major=1, revision=1, interface=None, *, provides=None, requires=None):
        def register(function):
            signature = inspect.signature(function)
            def handler(params, context):
                if not isinstance(params, dict):
                    raise PlatformError('invalid_params', 'Operation parameters must be an object')
                kwargs = dict(params)
                if 'ctx' in kwargs:
                    raise PlatformError('invalid_params', 'ctx is assigned by the platform')
                if 'ctx' in signature.parameters:
                    kwargs['ctx'] = context
                return function(**kwargs)
            super(Component, self).operation(name, access, major, revision, interface,
                                            provides=provides, requires=requires)(handler)
            return function
        return register

    def call(self, operation, params, context):
        exposed = context
        if not isinstance(context, _RemoteContext):
            bindings = self.port.requirements(operation) if self._operations.get(operation, {}).get('requires') else None
            exposed = _LocalContext(self.port, context, bindings)
        return super().call(operation, params, exposed)

    def run(self):
        serve(self)

    def resume_task(self, name):
        context = self.port.resume_task(name)
        return _LocalContext(self.port, context) if context is not None else None


class _RemoteContext:
    def __init__(self, peer, token):
        self._peer, self._token = peer, token

    def call_required(self, alias, params=None):
        return self._peer.request('call_required', {'alias': alias, 'params': params or {}, 'token': self._token})

    def subscribe_required(self, alias, callback):
        return self._peer.process_client._subscribe('subscribe_required', {'alias': alias}, callback, self)

    def subscribe(self, target, event, callback):
        return self._peer.process_client.subscribe(target, event, callback, context=self)

    def publish(self, event, payload):
        return self._peer.process_client.publish(event, payload, context=self)

    def unsubscribe(self, subscription):
        return self._peer.process_client.unsubscribe(subscription)

    def call(self, target, operation, params=None):
        return self._peer.request('call', {'target': target, 'operation': operation,
                                         'params': params or {}, 'token': self._token})


class _ProcessClient:
    def __init__(self, peer):
        self.peer = peer
        self.callbacks = {}

    def subscribe(self, target, event, callback, context=None):
        return self._subscribe('subscribe', {'target': target, 'event': event}, callback, context)

    def _subscribe(self, method, params, callback, context):
        if not isinstance(context, _RemoteContext):
            raise PlatformError('denied', 'Explicit request context is required')
        subscription = self.peer.request(method, {**params, 'token': context._token})
        self.callbacks[subscription] = callback
        return subscription

    def unsubscribe(self, subscription):
        self.callbacks.pop(subscription, None)
        return self.peer.request('unsubscribe', {'subscription': subscription})

    def publish(self, event, payload, context=None):
        if not isinstance(context, _RemoteContext):
            raise PlatformError('denied', 'Explicit request context is required')
        return self.peer.request('publish', {'event': event, 'payload': payload, 'token': context._token})

    def advertise(self):
        return self.peer.request('advertise')

    def call(self, target, operation, params=None, context=None):
        if not isinstance(context, _RemoteContext):
            raise PlatformError('denied', 'Explicit request context is required')
        return context.call(target, operation, params)


class _LocalContext:
    def __init__(self, port, context, bindings=None):
        self.port, self.context, self._bindings = port, context, bindings

    def call_required(self, alias, params=None):
        if self._bindings is None:
            raise PlatformError('missing_requirement', alias)
        return self._bindings.call(alias, params, self.context)

    def subscribe_required(self, alias, callback):
        if self._bindings is None:
            raise PlatformError('missing_requirement', alias)
        return self._bindings.subscribe(alias, self._delivery(callback), self.context)

    def _delivery(self, callback):
        def delivery(payload, context):
            return callback(payload, _LocalContext(self.port, context, self._bindings))
        return delivery

    def subscribe(self, target, event, callback):
        return self.port.subscribe(target, event, self._delivery(callback), context=self.context)

    def publish(self, event, payload):
        return self.port.publish(event, payload, context=self.context)

    def unsubscribe(self, subscription):
        return self.port.unsubscribe(subscription)

    def call(self, target, operation, params=None):
        return self.port.call(target, operation, params, context=self.context)

    def local_view_input(self, parent):
        return self.port.local_view_input(parent)

    def require_permissions(self, operations):
        self.port.require_permissions(operations, self.context)

    def remember_task(self, name, operations):
        self.port.remember_task(name, operations, self.context)

    def forget_task(self, name):
        self.port.forget_task(name, self.context)


def serve(component):
    """Serve protocol v1. Diagnostics and ordinary print calls go to stderr."""
    protocol_stdout = sys.stdout
    sys.stdout = sys.stderr
    done = threading.Event()
    holder = {}
    def dispatch(method, params):
        if method == 'hello':
            if params.get('platformApi') != 1:
                raise PlatformError('protocol', 'Unsupported platform protocol')
            return {'platformApi': 1}
        if method == 'describe':
            return component.describe()
        if method == 'start':
            component.start(holder['peer'].process_client)
            return None
        if method == 'event':
            callback = holder['peer'].process_client.callbacks.get(params['subscription'])
            if callback is None:
                raise PlatformError('unavailable', 'Subscription has ended')
            return callback(params.get('payload'), _RemoteContext(holder['peer'], params['token']))
        if method == 'call':
            context = _RemoteContext(holder['peer'], params['token'])
            expected = params.get('expected')
            token = _dispatched.set(tuple(expected) if expected else None)
            try:
                return component.call(params['operation'], params.get('params', {}), context)
            finally:
                _dispatched.reset(token)
        if method == 'stop':
            component.stop()
            done.set()
            return None
        raise PlatformError('protocol', 'Unknown protocol method')
    peer = _Peer(sys.stdin, protocol_stdout, dispatch, failed=done.set)
    holder['peer'] = peer
    peer.process_client = _ProcessClient(peer)
    try:
        done.wait()
        with peer.lock:
            workers = list(peer.workers)
        for worker in workers:
            worker.join(timeout=5)
    finally:
        peer.close()
        sys.stdout = protocol_stdout
