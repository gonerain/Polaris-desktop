"""Portable JSON-lines stdio transport. stdout is reserved for protocol frames."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from .protocol import PlatformError


MAX_FRAME_BYTES = 1024 * 1024
MAX_REQUESTS = 32


class _Peer:
    def __init__(self, reader, writer, handler, timeout=5.0, failed=None):
        self.reader, self.writer, self.handler = reader, writer, handler
        self.timeout, self.failed = timeout, failed
        self.pending = {}
        self.lock = threading.RLock()
        self.closed = False
        self.workers = set()
        self.slots = threading.BoundedSemaphore(MAX_REQUESTS)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _send(self, message):
        try:
            line = json.dumps(message, allow_nan=False, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise PlatformError('encoding', str(exc)) from exc
        if len(line.encode('utf-8')) + 1 > MAX_FRAME_BYTES:
            raise PlatformError('frame_too_large', 'Protocol frame exceeds 1 MiB')
        with self.lock:
            if self.closed:
                raise PlatformError('unavailable', 'Process connection is closed')
            try:
                self.writer.write(line + '\n')
                self.writer.flush()
            except (OSError, ValueError) as exc:
                raise PlatformError('unavailable', 'Process connection closed') from exc

    def request(self, method, params=None, timeout=None):
        rid = uuid.uuid4().hex
        ready = threading.Event()
        box = {}
        with self.lock:
            if self.closed:
                raise PlatformError('unavailable', 'Process connection is closed')
            if len(self.pending) >= MAX_REQUESTS:
                raise PlatformError('busy', 'Too many outstanding protocol requests')
            self.pending[rid] = (ready, box)
        try:
            self._send({'id': rid, 'method': method, 'params': params or {}})
            if not ready.wait(self.timeout if timeout is None else timeout):
                raise PlatformError('timeout', 'Process request timed out; result may have occurred')
            if 'error' in box:
                error = box['error']
                raise PlatformError(error['code'], error['message'], error.get('details'))
            return box.get('result')
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def _dispatch(self, frame):
        try:
            result = self.handler(frame['method'], frame.get('params', {}))
            response = {'id': frame['id'], 'result': result}
            # Validate before writing, so encoding failures return a protocol error.
            if len(json.dumps(response, allow_nan=False, ensure_ascii=False).encode('utf-8')) + 1 > MAX_FRAME_BYTES:
                raise PlatformError('frame_too_large', 'Protocol result exceeds 1 MiB')
        except PlatformError as exc:
            response = {'id': frame['id'], 'error': exc.as_dict()}
        except Exception as exc:
            response = {'id': frame['id'], 'error': {'code': 'handler_error', 'message': str(exc)}}
        try:
            self._send(response)
        except PlatformError:
            pass
        finally:
            with self.lock:
                self.workers.discard(threading.current_thread())
            self.slots.release()

    def _read(self):
        try:
            while True:
                line = self.reader.readline(MAX_FRAME_BYTES + 1)
                if not line:
                    break
                if len(line.encode('utf-8')) > MAX_FRAME_BYTES or not line.endswith('\n'):
                    raise ValueError('Protocol frame exceeds 1 MiB or is incomplete')
                def invalid_constant(value):
                    raise ValueError('Non-JSON numeric value')
                frame = json.loads(line, parse_constant=invalid_constant)
                if not isinstance(frame, dict) or not isinstance(frame.get('id'), str):
                    raise ValueError('Invalid protocol frame')
                if 'method' in frame:
                    if not isinstance(frame['method'], str) or not isinstance(frame.get('params', {}), dict):
                        raise ValueError('Invalid protocol request')
                    if not self.slots.acquire(blocking=False):
                        self._send({'id': frame['id'], 'error': {'code': 'busy', 'message': 'Too many concurrent protocol requests'}})
                        continue
                    worker = threading.Thread(target=self._dispatch, args=(frame,), daemon=True)
                    with self.lock:
                        self.workers.add(worker)
                    worker.start()
                else:
                    if 'error' in frame:
                        error = frame['error']
                        if not isinstance(error, dict) or not isinstance(error.get('code'), str) or not isinstance(error.get('message'), str):
                            raise ValueError('Invalid protocol error')
                    elif 'result' not in frame:
                        raise ValueError('Missing protocol result')
                    with self.lock:
                        pending = self.pending.get(frame['id'])
                        if pending:
                            pending[1].update(frame)
                            pending[0].set()
        except Exception:
            pass
        finally:
            self.close()
            if self.failed:
                self.failed()

    def close(self):
        with self.lock:
            self.closed = True
            for ready, box in self.pending.values():
                box.update(error={'code': 'unavailable', 'message': 'Process connection closed'})
                ready.set()


class ProcessComponent:
    """Runtime provider; never interprets business fields or grants permissions."""
    def __init__(self, manifest, directory, timeout=5.0):
        self.manifest, self.directory = manifest, Path(directory)
        self.timeout = timeout
        self.process = self.peer = self.port = None
        self.description = None
        self.tokens = {}
        self.token_lock = threading.RLock()
        self.call_lock = threading.Lock()
        self.failure_callback = None
        self.stopping = False
        self.call_failed = False
        self.active_requests = set()
        self.subscriptions = {}

    def set_failure_callback(self, callback):
        self.failure_callback = callback

    def _exited(self):
        self._clear_subscriptions()
        with self.token_lock:
            self.tokens.clear()
        if not self.stopping and self.failure_callback:
            self.failure_callback()

    def _ensure_process(self):
        if self.peer:
            return
        command = self.manifest['entry']['command']
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise PlatformError('manifest', 'Process command must be a nonempty string array')
        command = [sys.executable if part == '{python}' else part for part in command]
        self.call_failed = False
        self.stopping = False
        environment = os.environ.copy()
        inherited = environment.get('PYTHONPATH', '').split(os.pathsep) if environment.get('PYTHONPATH') else []
        paths = [str(Path(__file__).resolve().parents[1])]
        paths.extend(str(Path(part or '.').resolve()) for part in inherited)
        environment['PYTHONPATH'] = os.pathsep.join(dict.fromkeys(paths))
        self.process = subprocess.Popen(command, cwd=self.directory, env=environment, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=None, text=True,
                                        encoding='utf-8', bufsize=1, shell=False)
        self.peer = _Peer(self.process.stdout, self.process.stdin, self._reverse,
                          self.timeout, self._exited)
        try:
            hello = self.peer.request('hello', {'platformApi': 1})
            if hello != {'platformApi': 1}:
                raise PlatformError('protocol', 'Unsupported process protocol')
            self.description = self.peer.request('describe')
        except Exception:
            self.force_stop()
            raise

    def describe(self):
        self._ensure_process()
        if self.peer.closed:
            return self.description  # Historical metadata remains inspectable after failure.
        self.description = self.peer.request('describe')
        return self.description

    def start(self, port):
        self.port = port
        self._ensure_process()
        self.peer.request('start')

    def call(self, operation, params, context):
        request = getattr(context, 'request_id', id(context))
        with self.token_lock:
            if request in self.active_requests:
                raise PlatformError('call_cycle', 'Reentrant process call cycle is unsupported')
            self.active_requests.add(request)
        try:
            return self._call(operation, params, context)
        finally:
            with self.token_lock:
                self.active_requests.discard(request)

    def _call(self, operation, params, context):
        # A plugin receives only one live request token at a time, preventing a
        # concurrent invocation from borrowing another request's authority.
        with self.call_lock:
            if self.call_failed:
                raise PlatformError('unavailable', 'A previous process call timed out; stop this instance before restarting')
            token = uuid.uuid4().hex
            with self.token_lock:
                self.tokens[token] = context
            try:
                return self.peer.request('call', {'operation': operation, 'params': params, 'token': token})
            except PlatformError as exc:
                if exc.code == 'timeout':
                    self.call_failed = True
                raise
            finally:
                with self.token_lock:
                    self.tokens.pop(token, None)

    def _reverse(self, method, params):
        if method == 'unsubscribe':
            subscription = self.subscriptions.pop(params.get('subscription'), None)
            if subscription is not None and self.port is not None:
                self.port.unsubscribe(subscription)
            return None
        if method == 'advertise':
            if self.port is None:
                raise PlatformError('unavailable', 'Component is not started')
            self.port.advertise()
            return None
        with self.token_lock:
            token = params.get('token')
            if token not in self.tokens:
                raise PlatformError('denied', 'Missing or expired request context')
            context = self.tokens[token]
        if method == 'subscribe':
            subscription = uuid.uuid4().hex
            def deliver(payload, event_context):
                token = uuid.uuid4().hex
                with self.token_lock:
                    self.tokens[token] = event_context
                try:
                    return self.peer.request('event', {'subscription': subscription, 'payload': payload, 'token': token})
                finally:
                    with self.token_lock:
                        self.tokens.pop(token, None)
            host_token = self.port.subscribe(params['target'], params['event'], deliver, context=context)
            self.subscriptions[subscription] = host_token
            return subscription
        if method == 'publish':
            return self.port.publish(params['event'], params.get('payload'), context=context)
        if method == 'call':
            return self.port.call(params['target'], params['operation'], params.get('params', {}), context=context)
        raise PlatformError('protocol', 'Unsupported reverse request')

    def _clear_subscriptions(self):
        if self.port is not None:
            for subscription in list(self.subscriptions.values()):
                try:
                    self.port.unsubscribe(subscription)
                except PlatformError:
                    pass
        self.subscriptions.clear()

    def stop(self):
        self._clear_subscriptions()
        if not self.process:
            return
        self.stopping = True
        try:
            if self.process.poll() is None:
                try:
                    self.peer.request('stop')
                except PlatformError as exc:
                    if self.process.poll() is None:
                        raise PlatformError('stopping', 'Process did not acknowledge stop; force_stop is available') from exc
                try:
                    self.process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired as exc:
                    raise PlatformError('stopping', 'Process still stopping; force_stop is available') from exc
        finally:
            if self.process.poll() is not None:
                self._cleanup()

    def _cleanup(self):
        self.peer.close()
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass  # The peer may have exited before buffered stdin flushed.
        if threading.current_thread() is not self.peer.thread:
            self.peer.thread.join(timeout=self.timeout)
        self.peer = self.process = None
        self.port = None

    def force_stop(self):
        self._clear_subscriptions()
        if self.process:
            self.stopping = True
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=self.timeout)
            self._cleanup()
