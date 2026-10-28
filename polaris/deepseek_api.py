"""DeepSeek HTTP transport: credentials, rate limit, response parsing and cancellation."""
from collections import deque
import json
import os
import time

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"


class DeepSeekModel(QObject):
    def __init__(self, parent=None, *, manager=None):
        super().__init__(parent)
        self._network = manager or QNetworkAccessManager(self)
        self._key = ""
        self._reply = None
        self._epoch = 0
        self._calls = deque()
        self.notice = "未设置 DEEPSEEK_API_KEY，请设置环境变量后重新启动"
        try:
            value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            if value:
                self._key = self._valid_key(value)
                self.notice = "已加载环境变量 Key · 连接微信后按保存的偏好回复"
        except ValueError:
            self.notice = "DEEPSEEK_API_KEY 格式无效，请修改环境变量后重新启动"

    @property
    def has_key(self):
        return bool(self._key)

    def contains_secret(self, value):
        return bool(self._key) and self._key in value

    def redact(self, value):
        return value.replace(self._key, "[密钥已隐藏]") if self._key else value

    def cancel(self):
        self._epoch += 1
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()

    @staticmethod
    def _valid_key(value):
        if not isinstance(value, str) or not 8 <= len(value) <= 4096 or not value.isascii():
            raise ValueError("Key 格式无效")
        if any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError("Key 格式无效")
        return value

    def generate(self, messages, callback, *, tools=None):
        if not self.has_key:
            callback("", self.notice)
            return
        now = time.monotonic()
        while self._calls and self._calls[0] < now - 60:
            self._calls.popleft()
        if len(self._calls) >= 10:
            callback("", "每分钟最多10次模型请求，本轮停止")
            return
        self._calls.append(time.monotonic())
        request = QNetworkRequest(QUrl(ENDPOINT))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setTransferTimeout(90000)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Authorization", ("Bearer " + self._key).encode("ascii"))
        request.setRawHeader(b"User-Agent", b"Polaris-Weixin/0.1")
        data = {"model": MODEL, "messages": messages, "stream": False,
                "max_tokens": 1024, "thinking": {"type": "disabled"}}
        if tools:
            data["tools"] = tools
        epoch = self._epoch
        reply = self._network.post(request, json.dumps(data, ensure_ascii=False).encode("utf8"))
        self._reply = reply
        buffer = bytearray()
        oversized = False
        deadline = QTimer(reply)
        deadline.setSingleShot(True)
        deadline.timeout.connect(reply.abort)
        deadline.start(91000)

        def read():
            nonlocal oversized
            buffer.extend(bytes(reply.readAll()))
            if len(buffer) > 524288:
                oversized = True
                buffer.clear()
                reply.abort()

        def finish():
            deadline.stop()
            read()
            if self._reply is reply:
                self._reply = None
            reply.deleteLater()
            if epoch != self._epoch:
                return
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            error, answer = "", ""
            if oversized:
                error = "模型响应过大"
            elif status is not None and not 200 <= int(status) < 300:
                error = {401: "DeepSeek Key 无效", 402: "DeepSeek 余额不足", 429: "DeepSeek 请求限流"}.get(
                    int(status), "DeepSeek 请求失败（HTTP " + str(status) + "）")
            elif reply.error() != QNetworkReply.NoError:
                error = "DeepSeek 网络失败或超时"
            else:
                try:
                    result = json.loads(buffer)
                    message = result["choices"][0]["message"]
                    if not isinstance(message, dict):
                        raise ValueError()
                    calls = message.get("tool_calls")
                    if calls and tools:
                        if not isinstance(calls, list) or not 1 <= len(calls) <= 4:
                            raise ValueError()
                        answer = {"role": "assistant", "content": None, "tool_calls": calls}
                    else:
                        answer = message["content"]
                        if not isinstance(answer, str) or not answer.strip() or calls:
                            raise ValueError()
                        answer.encode("utf8")
                        answer = answer.replace(self._key, "[密钥已隐藏]")
                except (ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
                    error = "DeepSeek 未返回有效文字回复"
            callback(answer, error)

        reply.readyRead.connect(read)
        reply.finished.connect(finish)
