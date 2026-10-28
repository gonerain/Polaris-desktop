"""Bounded JSON Lines over Qt LocalSocket; only explicit methods are exposed."""
from collections import OrderedDict
import hmac
import json
import secrets
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer
from .bridge_paths import MAX_FRAME, endpoint_path, publish_endpoint, read_endpoint, socket_address
from .component_api import ApiError, arguments, text


def encode(value):
    encoded = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf8")
    if len(encoded) > MAX_FRAME:
        raise ApiError("result_too_large", "结果过大，请缩小查询范围；写操作可能已应用，勿自动重试")
    return encoded


class LocalBridge(QObject):
    def __init__(self, hub, components, parent=None):
        super().__init__(parent)
        self.hub, self.components = hub, components
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._peers = set()
        self._instances = {}
        self._token = ""
        self._endpoint = None
        self._temporary = None
        self._clock = QTimer(self)
        self._clock.setInterval(5000)
        self._clock.timeout.connect(self._check)
        hub.permissionRequested.connect(self._grant)

    def start(self, data_directory):
        try:
            if self.server.isListening():
                return
            address, self._temporary = socket_address()
            if not self.server.listen(address):
                raise OSError(self.server.errorString())
            self._token = secrets.token_hex(32)
            self._endpoint = endpoint_path(data_directory)
            publish_endpoint(self._endpoint, {"protocol": 1, "address": self.server.fullServerName(), "token": self._token})
            self._clock.start()
            self.hub.set_error("")
        except (OSError, ValueError) as error:
            self.stop()
            self.hub.set_error("本机接入未开启：" + str(error))

    def stop(self):
        self._clock.stop()
        for peer in list(self._peers):
            peer.close()
        self.server.close()
        if self._endpoint is not None:
            try:
                if read_endpoint(self._endpoint).get("token") == self._token:
                    self._endpoint.unlink()
            except (OSError, ValueError):
                pass
        self._endpoint = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self._peers) >= 32:
                socket.abort()
                socket.deleteLater()
            else:
                peer = _Peer(self, socket)
                self._peers.add(peer)

    def _check(self):
        now = time.monotonic()
        for peer in list(self._peers):
            if now - peer.last_seen > (45 if peer.instance else 5):
                peer.close()
        self.hub.prune()

    def _grant(self, instance, component, level):
        if instance in self._instances and level in ("none", "read", "write"):
            try:
                self.components.help(component)
            except ApiError:
                return
            self.hub.grant(instance, component, level)

    def dispatch(self, peer, message):
        if peer.instance is None:
            arguments(message, ("id", "method", "params"), ("id", "method", "params"))
            params = arguments(message["params"], ("protocol", "token", "instanceId", "name"),
                               ("protocol", "token", "instanceId", "name"))
            if (message["method"] != "hello" or type(params["protocol"]) is not int or params["protocol"] != 1
                    or not isinstance(params["token"], str) or not hmac.compare_digest(params["token"], self._token)):
                raise ApiError("authentication_failed", "认证失败或协议不兼容")
            instance = text(params["instanceId"], "instanceId", 128)
            name = text(params["name"], "name", 64)
            if instance in self._instances:
                raise ApiError("instance_in_use", "实例已有活跃连接，请使用独立 instanceId")
            peer.instance = instance
            peer._auth_timer.stop()
            self._instances[instance] = peer
            self.hub.connect_client(instance, name)
            return {"protocol": 1, "heartbeatSeconds": 15}
        if "event" in message:
            arguments(message, ("event", "data"), ("event", "data"))
            event = text(message["event"], "event", 64)
            self.hub.event(peer.instance, event, message["data"])
            return None
        arguments(message, ("id", "method", "params"), ("id", "method"))
        params = message.get("params", {})
        method = message["method"]
        if method == "heartbeat":
            arguments(params, ())
            return {"alive": True}
        if method == "components.list":
            arguments(params, ())
            return self.components.components
        if method == "components.help":
            arguments(params, ("component",), ("component",))
            return self.components.help(params["component"])
        if method == "components.call":
            arguments(params, ("component", "operation", "args"), ("component", "operation"))
            return self.components.call(params["component"], params["operation"], params.get("args", {}),
                                        self.hub.grants(peer.instance))
        raise ApiError("unknown_method", "方法未登记")


class _Peer(QObject):
    def __init__(self, bridge, socket):
        super().__init__(bridge)
        self.bridge, self.socket = bridge, socket
        self.instance = None
        self.last_seen = time.monotonic()
        self._buffer = bytearray()
        self._cache = OrderedDict()
        self._closed = False
        self._processing = False
        self._rate_start, self._rate_count = self.last_seen, 0
        socket.setReadBufferSize(MAX_FRAME * 2)
        socket.readyRead.connect(self._read)
        socket.disconnected.connect(self.close)
        self._auth_timer = QTimer(self)
        self._auth_timer.setSingleShot(True)
        self._auth_timer.timeout.connect(self._auth_timeout)
        self._auth_timer.start(5000)
        if socket.bytesAvailable():
            QTimer.singleShot(0, self._read)

    def _auth_timeout(self):
        if self.instance is None:
            self.close()

    def _read(self):
        if self._closed:
            return
        self._buffer.extend(bytes(self.socket.readAll()))
        if len(self._buffer) > MAX_FRAME * 2:
            self.close()
            return
        if not self._processing:
            self._processing = True
            self._process()

    def _process(self):
        if self._closed:
            return
        for _ in range(32):
            end = self._buffer.find(b"\n")
            if end < 0:
                if len(self._buffer) > MAX_FRAME:
                    self.close()
                self._processing = False
                return
            if end + 1 > MAX_FRAME:
                self.close()
                return
            line = bytes(self._buffer[:end])
            del self._buffer[:end + 1]
            now = time.monotonic()
            if now - self._rate_start >= 5:
                self._rate_start, self._rate_count = now, 0
            self._rate_count += 1
            if self._rate_count > 200:
                self.close()
                return
            self._message(line)
            if self._closed:
                return
        QTimer.singleShot(0, self._process)

    def _message(self, line):
        identity = None
        was_authenticated = self.instance is not None
        try:
            message = json.loads(line.decode("utf8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(message, dict):
                raise ValueError()
            identity = message.get("id")
            if "event" not in message:
                text(identity, "id", 128)
            if identity in self._cache:
                old_line, response = self._cache[identity]
                if line != old_line:
                    raise ApiError("id_conflict", "请求ID已用于不同内容")
                self._send(response)
                self.last_seen = time.monotonic()
                return
            result = self.bridge.dispatch(self, message)
            self.last_seen = time.monotonic()
            if identity is None:
                return
            response = encode({"id": identity, "ok": True, "result": result})
        except (UnicodeError, ValueError, TypeError, RecursionError):
            identity = identity if isinstance(identity, str) else None
            response = encode({"id": identity, "ok": False,
                               "error": {"code": "invalid_params", "message": "无效 JSON、消息格式或参数"}})
        except ApiError as error:
            identity = identity if isinstance(identity, str) else None
            response = encode({"id": identity, "ok": False, "error": {"code": error.code, "message": str(error)}})
        except Exception:
            # Never leak local paths, task data or credentials in a traceback.
            response = encode({"id": identity, "ok": False,
                               "error": {"code": "internal_error", "message": "本机操作失败，结果未知；先查询，勿自动重试修改"}})
        if isinstance(identity, str) and identity not in self._cache:
            self._cache[identity] = line, response
            while len(self._cache) > 16:
                self._cache.popitem(last=False)
        self._send(response)
        if not was_authenticated and self.instance is None:
            self.socket.disconnectFromServer()
        elif identity is None:
            # Malformed one-way events cannot be acknowledged safely: reconnect
            # and send a current snapshot rather than continuing with bad state.
            self.socket.disconnectFromServer()

    def _send(self, data):
        if self.socket.bytesToWrite() + len(data) > MAX_FRAME * 2:
            self.close()
            return
        self.socket.write(data)
        self.socket.flush()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._auth_timer.stop()
        self.bridge._peers.discard(self)
        if self.instance and self.bridge._instances.get(self.instance) is self:
            del self.bridge._instances[self.instance]
            self.bridge.hub.disconnect_client(self.instance)
        self.socket.abort()
        self.socket.deleteLater()
        self.deleteLater()
