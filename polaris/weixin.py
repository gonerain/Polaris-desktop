"""Standalone iLink text client. No agent, component API or business-event routing."""
import base64
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
import json
import math
import secrets
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .weixin_credentials import CredentialStore

BASE_URL = "https://ilinkai.weixin.qq.com"
PROTOCOL_VERSION = "2.4.10"  # Compatibility reference, not a claim to run OpenClaw.
MAX_RESPONSE = 2 * 1024 * 1024


def trusted_origin(value):
    parsed = urlsplit(value if isinstance(value, str) else "")
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or not (host == "weixin.qq.com" or host.endswith(".weixin.qq.com"))
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("微信返回了不受信任的服务地址")
    return "https://" + host


def string(value, limit, *, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError("微信响应字段不完整")
    value.encode("utf8")
    return value


def message_timestamp(message, items):
    """iLink may encode uint64 fields as strings or provide time on text items."""
    values = [message.get("create_time_ms")]
    values.extend(item.get("create_time_ms") for item in items if isinstance(item, dict))
    for value in values:
        if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 15:
            value = int(value)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and 0 < value < 1e15 and math.isfinite(value)):
            return float(value)
    return 0.0


class WeixinClient(QObject):
    changed = Signal()
    messagesChanged = Signal()
    textReceived = Signal(str, str, float)

    def __init__(self, parent=None, *, credential_path=None, manager=None, component_registry=None):
        super().__init__(parent)
        self._network = manager or QNetworkAccessManager(self)
        self._store = CredentialStore(credential_path)
        self._account = {}
        self._state, self._detail, self._warning = "offline", "微信未连接", ""
        self._qr_image, self._qr_token, self._qr_base = "", "", BASE_URL
        self._login_deadline = 0
        self._generation = 0
        self._replies = set()
        self._messages, self._seen = [], OrderedDict()
        self._context, self._sending, self._persisted = "", False, False
        self._retry = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        try:
            account = self._store.load()
            if account:
                self._validate_account(account)
                self._account = account
                self._persisted = True
                self._detail = "已保存绑定，点击连接后开始接收消息"
                for key in account.get("seen", [])[-512:]:
                    if isinstance(key, str) and len(key) <= 256:
                        self._seen[key] = True
        except (OSError, ValueError, TypeError, UnicodeError):
            self._warning = "已保存的微信凭证无法读取，请重新绑定或退出登录清除"
        from .deepseek_chat import DeepSeekChat
        self._model_chat = DeepSeekChat(self, registry=component_registry, state_path=(
            self._store.path.with_name("weixin-chat.json") if self._store.path is not None else None))

    modelChat = Property(QObject, lambda self: self._model_chat, constant=True)

    state = Property(str, lambda self: self._state, notify=changed)
    detail = Property(str, lambda self: self._detail, notify=changed)
    warning = Property(str, lambda self: self._warning, notify=changed)
    qrImage = Property(str, lambda self: self._qr_image, notify=changed)
    accountId = Property(str, lambda self: self._account.get("botId", ""), notify=changed)
    userId = Property(str, lambda self: self._account.get("userId", ""), notify=changed)
    hasAccount = Property(bool, lambda self: bool(self._account), notify=changed)
    persisted = Property(bool, lambda self: self._persisted, notify=changed)
    sending = Property(bool, lambda self: self._sending, notify=changed)
    canSend = Property(bool, lambda self: self._state == "connected" and bool(self._context)
                       and not self._sending, notify=changed)
    messages = Property("QVariantList", lambda self: [dict(row) for row in self._messages], notify=messagesChanged)

    @staticmethod
    def _validate_account(account):
        for key, limit in (("token", 8192), ("botId", 256), ("userId", 256)):
            string(account.get(key), limit)
        if not account["token"].isascii() or any(ord(char) < 33 or ord(char) == 127 for char in account["token"]):
            raise ValueError("无效微信凭证")
        trusted_origin(account.get("baseUrl"))
        string(account.get("cursor", ""), 65536, required=False)
        if not isinstance(account.get("seen", []), list):
            raise ValueError("无效去重记录")

    def _status(self, state, detail):
        self._state, self._detail = state, detail
        self.changed.emit()

    def _cancel(self):
        if hasattr(self, "_model_chat"):
            self._model_chat.suspend()
        self._generation += 1
        self._timer.stop()
        if self._sending:
            for row in self._messages:
                if row["status"] == "发送中":
                    row["status"] = "结果未知，请在微信核实"
            self.messagesChanged.emit()
        self._sending = False
        self._qr_image = self._qr_token = ""
        self._verify_code = ""
        for reply in list(self._replies):
            reply.abort()

    @Slot()
    def login(self):
        if self._account:
            self._warning = "更换绑定前请先退出登录"
            self.changed.emit()
            return
        self._cancel()
        self._warning = ""
        self._login_deadline = time.monotonic() + 300
        self._qr_base = BASE_URL
        self._status("loading", "正在获取微信登录二维码")
        self._request(BASE_URL, "ilink/bot/get_bot_qrcode?bot_type=3", {"local_token_list": []},
                      self._got_qr)

    def _got_qr(self, data, error):
        if error:
            self._status("error", "获取二维码失败，请重试（" + error + "）")
            return
        try:
            token = string(data.get("qrcode"), 8192)
            content = string(data.get("qrcode_img_content"), 2048)
            if not content.isascii():
                raise ValueError("二维码链接必须使用 URL 编码")
            # Encode the login URL locally; do not download an arbitrary QR image URL.
            url = urlsplit(content)
            trusted_origin("https://" + (url.netloc or ""))
            if url.scheme != "https":
                raise ValueError("二维码地址必须使用 HTTPS")
            import qrcode
            import qrcode.image.svg
            output = BytesIO()
            qrcode.make(content, image_factory=qrcode.image.svg.SvgPathImage, border=4).save(output)
            self._qr_image = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()
            self._qr_token = token
        except ImportError:
            self._status("error", "缺少二维码依赖，请安装 requirements.txt 后重启")
            return
        except (ValueError, TypeError, UnicodeError):
            self._status("error", "微信返回的二维码无效，请重试")
            return
        self._status("waiting", "在微信启用 ClawBot 后扫码，并在手机上确认绑定")
        self._timer.start(1)

    def _tick(self):
        if self._qr_token:
            if time.monotonic() >= self._login_deadline:
                self._qr_token = self._qr_image = ""
                self._status("error", "登录已超时，请重新获取二维码")
                return
            query = {"qrcode": self._qr_token}
            code = getattr(self, "_verify_code", "")
            if code:
                query["verify_code"] = code
                self._verify_code = ""
            self._request(self._qr_base, "ilink/bot/get_qrcode_status?" + urlencode(query),
                          None, self._qr_status, timeout=40000)
        elif self._account and self._state in ("connecting", "connected", "reconnecting"):
            self._request(self._account["baseUrl"], "ilink/bot/getupdates",
                          {"get_updates_buf": self._account.get("cursor", "")}, self._updates,
                          authenticated=True, timeout=45000)

    @Slot(str)
    def verify(self, code):
        if self._state != "verify" or not code.isascii() or not code.isdigit() or not 4 <= len(code) <= 12:
            return
        self._verify_code = code
        self._status("waiting", "正在验证配对码")
        self._timer.start(1)

    def _qr_status(self, data, error):
        if time.monotonic() >= self._login_deadline:
            self._qr_image = self._qr_token = ""
            self._status("error", "登录已超时，请重新获取二维码")
            return
        if error:
            self._detail = "登录网络暂不可用，正在重试（" + error + "）"
            self.changed.emit()
            self._timer.start(3000)
            return
        state = data.get("status")
        try:
            if state == "confirmed":
                account = {"token": data.get("bot_token"), "botId": data.get("ilink_bot_id"),
                           "userId": data.get("ilink_user_id"),
                           "baseUrl": trusted_origin(data.get("baseurl") or BASE_URL), "cursor": ""}
                self._validate_account(account)
                self._account = account
                self._qr_token = self._qr_image = ""
                self._save()
                self.connectAccount()
                return
            if state == "scaned_but_redirect":
                host = string(data.get("redirect_host"), 256)
                self._qr_base = trusted_origin(host if "://" in host else "https://" + host)
            elif state == "need_verifycode":
                self._status("verify", "输入手机微信显示的配对码")
                return
            elif state in ("expired", "verify_code_blocked", "binded_redirect"):
                self._qr_image = self._qr_token = ""
                self._status("error", "二维码已失效或绑定未返回凭证，请重新扫码；必要时先在微信解除旧绑定")
                return
            elif state not in ("wait", "scaned"):
                raise ValueError("未知登录状态")
        except (ValueError, TypeError, UnicodeError):
            self._qr_token = self._qr_image = ""
            self._status("error", "微信登录响应不完整或地址不受信任，请重新绑定")
            return
        self._status("waiting", "已扫码，请在手机确认" if state == "scaned" else "等待微信扫码确认")
        self._timer.start(1000)

    @Slot()
    def connectAccount(self):
        if not self._account:
            return
        self._cancel()
        self._retry = 0
        self._status("connecting", "正在连接微信")
        self._timer.start(1)

    @Slot()
    def disconnectAccount(self):
        self._cancel()
        self._context = ""
        self._status("offline", "已断开，绑定保留；连接后继续接收")

    @Slot()
    def logout(self):
        self._cancel()
        self._account = {}
        self._context = ""
        self._seen.clear()
        self._messages.clear()
        self._persisted = False
        self._warning = ""
        try:
            self._store.clear()
        except OSError:
            self._warning = "无法删除本机凭证文件，请检查目录权限；下次启动仍可能读到旧绑定"
        self.messagesChanged.emit()
        self._status("offline", "本机已退出；如需撤销平台授权，请在微信 ClawBot 中解除绑定")

    def _save(self):
        try:
            self._account["seen"] = list(self._seen)[-512:]
            self._persisted = self._store.save(self._account)
            if not self._persisted:
                self._warning = "当前仅在内存保存绑定，关闭程序后需重新扫码"
            else:
                self._warning = ""
        except (OSError, ValueError, TypeError):
            self._persisted = False
            self._warning = "无法加密保存绑定进度，本次仍可使用；重启可能需重新扫码或收到重复消息"
        self.changed.emit()

    def _updates(self, data, error):
        if data.get("ret") == -14 or data.get("errcode") == -14 or error in ("HTTP 401", "HTTP 403"):
            self._context = ""
            self._status("expired", "微信登录已失效，请退出登录后重新扫码")
            return
        if error:
            self._retry = min(self._retry + 1, 6)
            self._status("reconnecting", "微信连接中断，自动重试（" + error + "）")
            self._timer.start(min(60000, 1000 * 2 ** self._retry))
            return
        try:
            messages = data.get("msgs", [])
            if not isinstance(messages, list) or len(messages) > 1000:
                raise ValueError("消息格式无效")
            cursor = string(data.get("get_updates_buf", self._account.get("cursor", "")), 65536, required=False)
            previous_seen = list(self._seen)
            for message in messages:
                self._receive(message)
            if cursor != self._account.get("cursor") or previous_seen != list(self._seen):
                self._account["cursor"] = cursor
                self._save()
        except (ValueError, TypeError, UnicodeError):
            self._status("error", "微信消息格式不支持，已停止接收；请重连或升级组件")
            return
        self._retry = 0
        self._status("connected", "已连接 · 仅绑定者单聊")
        self._timer.start(500)  # Avoid a tight loop if the upstream returns immediately.

    def _receive(self, message):
        if not isinstance(message, dict) or message.get("group_id") or message.get("message_type") != 1:
            return
        sender = message.get("from_user_id")
        if not isinstance(sender, str) or sender.casefold() != self._account["userId"].casefold():
            return
        if message.get("message_state") in (0, 1):
            return
        identity = message.get("message_id")
        if isinstance(identity, int) and not isinstance(identity, bool):
            identity = str(identity)
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            return  # Never process an incoming message we cannot reliably deduplicate.
        context = message.get("context_token")
        if isinstance(context, str) and 0 < len(context) <= 16384:
            self._context = context
        if identity in self._seen:
            return
        items = message.get("item_list", [])
        if not isinstance(items, list):
            return
        parts = []
        for item in items[:100]:
            if not isinstance(item, dict):
                continue
            value = item.get("text_item")
            if item.get("type") == 1 and isinstance(value, dict) and isinstance(value.get("text"), str):
                parts.append(value["text"][:8000])
            else:
                parts.append("[暂不支持的消息类型]")
        body = "\n".join(parts)[:8000]
        body.encode("utf8")
        self._seen[identity] = True
        if len(self._seen) > 512:
            self._seen.popitem(last=False)
        if body:
            self._append(identity, body, "in", "已接收")
            if all(isinstance(item, dict) and item.get("type") == 1 for item in items):
                self.textReceived.emit(identity, body, message_timestamp(message, items))

    def _append(self, identity, body, direction, status):
        self._messages.append({"id": identity, "text": body, "direction": direction,
                               "status": status, "time": datetime.now().strftime("%H:%M")})
        del self._messages[:-100]
        self.messagesChanged.emit()

    @Slot(str, result=bool)
    def sendText(self, body):
        return self._send_text(body)

    def _send_text(self, body, callback=None):
        if (not self.canSend or not isinstance(body, str) or not body.strip() or len(body) > 2000):
            return False
        try:
            body.encode("utf8")
        except UnicodeError:
            return False
        identity = "polaris-" + uuid4().hex
        self._sending = True
        self._append(identity, body, "out", "发送中")
        self.changed.emit()

        def sent(data, error):
            # iLink success may be {} or contain only a message ID. ret is optional.
            if not error and (data.get("ret", 0) != 0 or data.get("errcode", 0) != 0):
                error = "微信接口拒绝发送"
            self._sending = False
            for row in self._messages:
                if row["id"] == identity:
                    row["status"] = ("发送结果未知，请在微信核实" if error else "已发送")
                    if error:
                        row["failureReason"] = error
            if error:
                self._warning = "发送未确认，不会自动重发（" + error + "）"
            self.messagesChanged.emit()
            self.changed.emit()
            if callback is not None:
                callback(not error)

        self._request(self._account["baseUrl"], "ilink/bot/sendmessage", {"msg": {
            "from_user_id": "", "to_user_id": self._account["userId"], "client_id": identity,
            "message_type": 2, "message_state": 2, "context_token": self._context,
            "item_list": [{"type": 1, "text_item": {"text": body}}]}}, sent, authenticated=True)
        return True

    @Slot()
    def clearMessages(self):
        self._model_chat.resetConversation()
        self._messages.clear()
        self.messagesChanged.emit()

    def _request(self, origin, endpoint, body, callback, *, authenticated=False, timeout=15000):
        # Never follow an HTTP redirect with bot credentials or accept non-Weixin API origins.
        origin = trusted_origin(origin)
        request = QNetworkRequest(QUrl(origin + "/" + endpoint))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setTransferTimeout(timeout)
        request.setRawHeader(b"iLink-App-Id", b"bot")
        request.setRawHeader(b"iLink-App-ClientVersion", str((2 << 16) | (4 << 8) | 10).encode())
        request.setRawHeader(b"User-Agent", b"Polaris-Weixin/0.1")
        if body is not None:
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setRawHeader(b"AuthorizationType", b"ilink_bot_token")
            request.setRawHeader(b"X-WECHAT-UIN", base64.b64encode(str(secrets.randbits(32)).encode()))
        if authenticated:
            request.setRawHeader(b"Authorization", ("Bearer " + self._account["token"]).encode())
            body = {**body, "base_info": {"channel_version": PROTOCOL_VERSION, "bot_agent": "Polaris/0.1"}}
        generation = self._generation
        reply = (self._network.get(request) if body is None else
                 self._network.post(request, json.dumps(body, ensure_ascii=False).encode("utf8")))
        self._replies.add(reply)
        chunks = bytearray()
        oversized = False
        timed_out = False
        deadline = QTimer(reply)
        deadline.setSingleShot(True)

        def timeout_reached():
            nonlocal timed_out
            timed_out = True
            reply.abort()

        deadline.timeout.connect(timeout_reached)
        deadline.start(timeout + 1000)

        def read():
            nonlocal oversized
            chunks.extend(bytes(reply.readAll()))
            if len(chunks) > MAX_RESPONSE:
                oversized = True
                chunks.clear()
                reply.abort()

        def finish():
            deadline.stop()
            read()
            self._replies.discard(reply)
            if generation != self._generation:
                reply.deleteLater()
                return
            result, error = {}, ""
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if oversized:
                error = "响应过大"
            elif (endpoint == "ilink/bot/getupdates" and
                  (timed_out or reply.error() == QNetworkReply.TimeoutError)):
                # Long polling can finish without a message; this is not a disconnect.
                result = {"msgs": []}
            elif status is not None and not 200 <= int(status) < 300:
                error = "HTTP " + str(status)
            elif reply.error() != QNetworkReply.NoError:
                error = "网络失败或超时"
            else:
                try:
                    result = json.loads(chunks)
                    if not isinstance(result, dict):
                        raise ValueError()
                    if result.get("ret", 0) != 0 or result.get("errcode", 0) != 0:
                        error = "微信接口拒绝请求"
                except (ValueError, UnicodeError):
                    result, error = {}, "响应格式无效"
            reply.deleteLater()
            callback(result, error)

        reply.readyRead.connect(read)
        reply.finished.connect(finish)
