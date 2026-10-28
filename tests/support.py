"""Explicit Qt test setup and fake transport; importing this module starts no app."""
import json
import os

from PySide6.QtCore import QObject, QEventLoop, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QNetworkReply


def initialize_qt_tests():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QUICK_BACKEND"] = "software"
    os.environ["DEEPSEEK_API_KEY"] = "test-only-fake-key"
    return QGuiApplication.instance() or QGuiApplication([])


def pump(milliseconds=20):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


class FakeReply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.buffer = b""
        self.status = 200
        self.failure = QNetworkReply.NoError

    def readAll(self):
        value, self.buffer = self.buffer, b""
        return value

    def error(self):
        return self.failure

    def attribute(self, _):
        return self.status

    def abort(self):
        self.failure = QNetworkReply.OperationCanceledError
        self.finished.emit()

    def complete(self, message):
        self.buffer = json.dumps({"choices": [{"message": message}]}).encode()
        self.readyRead.emit()
        self.finished.emit()


class FakeNetwork(QObject):
    def __init__(self):
        super().__init__()
        self.posts = []

    def post(self, request, data):
        reply = FakeReply(self)
        self.posts.append((request, json.loads(bytes(data)), reply))
        return reply
