"""Private authenticated loopback NDJSON bridge; no platform API forwarding."""
import json
import copy
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import tempfile
import time
import uuid
from .model import session_key, text

MAX_FRAME = 1024 * 1024


class Bridge:
    def __init__(self, store, directory):
        self.store = store
        self.directory = Path(directory)
        self.endpoint = self.directory / 'endpoint.json'
        self.token = secrets.token_urlsafe(32)
        self.peers = {}
        self._workers = set()
        self._connections = set()
        self.lock = threading.RLock()
        self.closed = False
        self.slots = threading.BoundedSemaphore(32)
        self.delivery_timeout = 30.0
        if self.directory.is_symlink():
            raise ValueError('bridge directory must not be a symlink')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        lock_path = self.directory / 'bridge.lock'
        if lock_path.is_symlink():
            raise ValueError('bridge lock must not be a symlink')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self._instance_lock = os.fdopen(fd, 'r+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self._instance_lock.write(b'0')
                self._instance_lock.flush()
                self._instance_lock.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._instance_lock.close()
            raise ValueError('Agent bridge is already running in this data directory') from error
        self.server = socket.socket()
        try:
            self.server.bind(('127.0.0.1', 0))
            self.server.listen(16)
            self.server.settimeout(.2)
        except Exception:
            self.server.close()
            self._instance_lock.close()
            raise
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False, mode='w', encoding='utf-8') as output:
                temporary = output.name
                json.dump({'version': 1, 'host': '127.0.0.1', 'port': self.server.getsockname()[1], 'token': self.token}, output)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.endpoint)
        except Exception:
            self.server.close()
            self._instance_lock.close()
            raise
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.closed:
            try:
                self._expire_deliveries()
            except (OSError, ValueError) as error:
                print(f'Agent delivery timeout state could not be saved: {error}', file=sys.stderr)
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.slots.acquire(blocking=False):
                connection.close()
                continue
            worker = threading.Thread(target=self._serve, args=(connection,), daemon=True)
            with self.lock:
                self._workers.add(worker)
                self._connections.add(connection)
            worker.start()

    def _expire_deliveries(self):
        with self.lock, self.store.transaction():
            expired = set()
            for delivery in self.store.deliveries.values():
                if delivery['status'] == 'pending' and time.time() - delivery.get('createdAt', 0) >= self.delivery_timeout:
                    delivery['status'] = 'unknown'
                    expired.add(tuple(delivery['owner']))
            if expired:
                self.store.changed()
            for identity in expired:
                peer = self.peers.get(identity)
                if peer:
                    try:
                        peer['socket'].shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

    @staticmethod
    def write(peer, value):
        data = (json.dumps(value, ensure_ascii=False) + '\n').encode()
        if len(data) > MAX_FRAME:
            raise ValueError('frame too large')
        with peer['lock']:
            peer['socket'].sendall(data)

    def _serve(self, connection):
        peer = {'socket': connection, 'lock': threading.Lock()}
        identity = None
        try:
            connection.settimeout(5)
            stream = connection.makefile('rb')
            first = stream.readline(MAX_FRAME + 1)
            if len(first) > MAX_FRAME or not first.endswith(b'\n'):
                return
            hello = json.loads(first)
            if not isinstance(hello, dict):
                return
            if hello.get('type') != 'hello' or not secrets.compare_digest(str(hello.get('token', '')), self.token):
                return
            adapter = text(hello.get('adapter'), 'adapter', 64)
            client_id = text(hello.get('clientId'), 'clientId', 256)
            identity = (adapter, client_id)
            with self.lock:
                previous = self.peers.get(identity)
                if previous:
                    with self.store.transaction():
                        for delivery in self.store.deliveries.values():
                            if delivery.get('owner') == list(identity) and delivery['status'] == 'pending':
                                delivery['status'] = 'unknown'
                        self.store.changed()
                    try:
                        previous['socket'].shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    previous['socket'].close()
                self.peers[identity] = peer
            self.write(peer, {'type': 'hello', 'ok': True})
            connection.settimeout(None)
            while not self.closed:
                line = stream.readline(MAX_FRAME + 1)
                if not line or len(line) > MAX_FRAME or not line.endswith(b'\n'):
                    break
                frame = json.loads(line)
                if not isinstance(frame, dict):
                    break
                try:
                    with self.lock:
                        if self.peers.get(identity) is not peer:
                            break
                        result = self._frame(identity, peer, frame)
                    if frame.get('type') == 'request':
                        self.write(peer, {'type': 'response', 'requestId': frame.get('requestId'), 'result': result})
                except (ValueError, KeyError) as error:
                    self.write(peer, {'type': 'response', 'requestId': frame.get('requestId'), 'error': str(error)})
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        finally:
            self.slots.release()
            connection.close()
            with self.lock:
                try:
                    if identity and self.peers.get(identity) is peer:
                        del self.peers[identity]
                        with self.store.transaction():
                            for row in self.store.rows.values():
                                if (row['adapter'], row['clientId']) == identity:
                                    row.update(online=False, canSend=False)
                            for delivery in self.store.deliveries.values():
                                if delivery.get('owner') == list(identity) and delivery['status'] == 'pending':
                                    delivery['status'] = 'unknown'
                            self.store.changed()
                except (OSError, ValueError) as error:
                    print(f'Agent disconnect state could not be saved: {error}', file=sys.stderr)
                finally:
                    self._connections.discard(connection)
                    self._workers.discard(threading.current_thread())

    def _frame(self, identity, peer, frame):
        adapter, client_id = identity
        if frame.get('type') == 'event':
            event = frame.get('event')
            if event == 'command.result':
                with self.store.transaction():
                    delivery = self.store.deliveries.get(frame.get('requestId'))
                    if delivery is None or delivery['owner'] != list(identity) or delivery['status'] != 'pending':
                        raise ValueError('unclaimed delivery')
                    status = frame.get('status')
                    if status not in ('accepted', 'rejected', 'unknown'):
                        raise ValueError('invalid delivery status')
                    delivery.update(status=status, detail=str(frame.get('detail', ''))[:4096])
                    if frame.get('turnId') is not None:
                        delivery['turnId'] = text(frame['turnId'], 'turnId')
                    self.store.changed()
                return copy.deepcopy(delivery)
            sid = text(frame.get('sessionId'), 'sessionId')
            key = session_key(adapter, client_id, sid)
            if event == 'session.snapshot':
                return self.store.snapshot(adapter, client_id, sid, **{k: frame[k] for k in ('title', 'cwd', 'canSend', 'liveness') if k in frame})
            if event == 'session.removed':
                with self.store.transaction():
                    self.store.require(key).update(online=False, canSend=False)
                    self.store.changed()
                return None
            if event == 'run.ended' and frame.get('status') not in ('completed', 'failed', 'stopped', 'unknown'):
                raise ValueError('invalid run status')
            if event in ('run.started', 'run.ended'):
                return self.store.run_event(key, frame.get('runId'), frame.get('status') if event == 'run.ended' else None, frame.get('reply'), frame.get('detail', ''), frame.get('replyTruncated', False))
            raise ValueError('unknown event')
        if frame.get('type') != 'request':
            raise ValueError('invalid frame')
        params = frame.get('params') or {}
        if not isinstance(params, dict) or 'session_id' in params:
            raise ValueError('invalid bridge params; use native sessionId')
        operation = frame.get('operation')
        scoped = ('session.mark', 'session.unmark', 'session.status', 'session.reply', 'session.send')
        key = session_key(adapter, client_id, text(params.get('sessionId'), 'sessionId')) if operation in scoped else None
        if operation == 'session.list':
            return [r for r in self.store.sessions() if (r['adapter'], r['clientId']) == identity]
        if operation in ('session.mark', 'session.unmark'):
            return self.store.mark(key, operation == 'session.mark')
        if operation == 'session.status':
            return self.store.status(key)
        if operation == 'session.reply':
            return self.store.result(key, params.get('runId'))
        if operation == 'session.send':
            return self.send(key, params.get('text'), params.get('deliveryId'), params.get('mode'))
        if operation == 'session.delivery':
            result = self.store.delivery(params['deliveryId'])
            if result['owner'] != list(identity):
                raise ValueError('wrong delivery owner')
            return result
        raise ValueError('unknown operation')

    def send(self, session_id, message, delivery_id=None, mode=None):
        if mode not in ('start', 'steer'):
            raise ValueError('mode must be start or steer')
        text(message, 'message', 128000)
        delivery_id = text(delivery_id, 'deliveryId', 256) if delivery_id is not None else uuid.uuid4().hex
        with self.lock, self.store.transaction():
            row = self.store.require(session_id)
            existing = self.store.deliveries.get(delivery_id)
            if existing:
                if existing['sessionId'] != session_id or existing['text'] != message or existing.get('mode', 'start') != mode:
                    raise ValueError('deliveryId already used')
                return copy.deepcopy(existing)
            if not row['marked'] or not row['online'] or not row['canSend']:
                raise ValueError('session is not marked and online with send capability')
            identity = (row['adapter'], row['clientId'])
            peer = self.peers.get(identity)
            if not peer:
                raise ValueError('host offline')
            if sum(d['status'] == 'pending' for d in self.store.deliveries.values()) >= 32:
                raise ValueError('too many pending deliveries')
            delivery = {'id': delivery_id, 'sessionId': session_id, 'owner': list(identity), 'text': message, 'mode': mode, 'status': 'pending', 'createdAt': time.time()}
            self.store.deliveries[delivery_id] = delivery
            self.store.changed()
            command = {'type': 'command', 'command': 'session.send', 'requestId': delivery_id, 'sessionId': row['sessionId'], 'text': message, 'mode': mode}
            def dispatch():
                try:
                    self.write(peer, command)
                except (OSError, ValueError):
                    with self.store.transaction():
                        current = self.store.deliveries.get(delivery_id)
                        if current is not None and current['status'] == 'pending':
                            current['status'] = 'unknown'
                            self.store.changed()
            threading.Thread(target=dispatch, daemon=True).start()
            return copy.deepcopy(delivery)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.server.close()
        self.thread.join(1)
        with self.lock:
            connections = list(self._connections)
            workers = list(self._workers)
            for connection in connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        deadline = time.monotonic() + 2
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(max(0, deadline - time.monotonic()))
        try:
            if not self.endpoint.is_symlink() and json.loads(self.endpoint.read_text())['token'] == self.token:
                self.endpoint.unlink()
        except (OSError, ValueError, KeyError):
            pass
        self._instance_lock.close()
