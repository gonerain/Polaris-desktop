"""Explicit cross-WSL byte relay. No GUI, second app lock, shell or TCP listener."""
import argparse
import json
import os
import sys
import threading

from PySide6.QtCore import QCoreApplication, QObject, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalSocket
from .bridge_paths import MAX_FRAME, endpoint_path, read_endpoint


def _stdio_fd(stream, standard_handle):
    if stream is not None:
        try:
            return stream.fileno()
        except (OSError, ValueError):
            pass
    if os.name == "nt":
        # Windowed PyInstaller may expose sys.stdin/stdout as None even though
        # the caller supplied real pipe handles. Reopen only those handles.
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel.GetStdHandle(standard_handle & 0xFFFFFFFF)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OSError("标准输入/输出必须由调用方重定向")
        return msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDONLY if standard_handle == -10 else os.O_WRONLY))
    raise OSError("缺少标准输入/输出")


class _Input(QObject):
    data = Signal(bytes)
    ended = Signal()


def run_relay(argv):
    parser = argparse.ArgumentParser(description="Polaris 本机标准输入/输出连接助手")
    parser.add_argument("--bridge-stdio", action="store_true")
    parser.add_argument("--endpoint")
    options = parser.parse_args(argv)
    app = QCoreApplication([])
    app.setApplicationName("Polaris")
    app.setOrganizationName("Polaris")
    try:
        document = read_endpoint(options.endpoint or endpoint_path())
        incoming = _stdio_fd(sys.stdin, -10)
        outgoing = _stdio_fd(sys.stdout, -11)
        if os.name == "nt":
            import msvcrt
            msvcrt.setmode(incoming, os.O_BINARY)
            msvcrt.setmode(outgoing, os.O_BINARY)
        socket = QLocalSocket(app)
        socket.connectToServer(document["address"])
        if not socket.waitForConnected(5000):
            raise OSError(socket.errorString())
    except (OSError, ValueError, TypeError, AttributeError) as error:
        if sys.stderr is not None:
            print("Polaris relay: " + str(error), file=sys.stderr)
        return 2
    pump = _Input(app)
    slots = threading.Semaphore(8)
    buffer = bytearray()
    authenticated = False
    failed = False

    def fail():
        nonlocal failed
        failed = True
        socket.abort()
        app.quit()

    def forward(data):
        nonlocal authenticated
        slots.release()
        buffer.extend(data)
        if len(buffer) > MAX_FRAME * 2:
            fail()
            return
        while b"\n" in buffer:
            end = buffer.index(b"\n")
            if end + 1 > MAX_FRAME:
                fail()
                return
            line = bytes(buffer[:end + 1])
            del buffer[:end + 1]
            if not authenticated:
                try:
                    hello = json.loads(line)
                    if hello.get("method") != "hello" or not isinstance(hello.get("params"), dict):
                        raise ValueError()
                    hello["params"]["token"] = document["token"]
                    line = (json.dumps(hello, ensure_ascii=False) + "\n").encode("utf8")
                except (ValueError, TypeError, AttributeError):
                    fail()
                    return
                authenticated = True
            if len(line) > MAX_FRAME or socket.bytesToWrite() + len(line) > MAX_FRAME * 2:
                fail()
                return
            socket.write(line)
            socket.flush()
        if len(buffer) > MAX_FRAME:
            fail()

    def receive():
        try:
            data = bytes(socket.readAll())
            while data:
                count = os.write(outgoing, data)
                if count <= 0:
                    raise OSError("标准输出已关闭")
                data = data[count:]
        except OSError:
            fail()

    def produce():
        try:
            while True:
                data = os.read(incoming, 4096)
                if not data:
                    break
                slots.acquire()
                pump.data.emit(data)
        except OSError:
            pass
        pump.ended.emit()

    pump.data.connect(forward)
    pump.ended.connect(socket.disconnectFromServer)
    socket.readyRead.connect(receive)
    socket.disconnected.connect(app.quit)
    socket.errorOccurred.connect(lambda _: fail())
    thread = threading.Thread(target=produce, daemon=True)
    thread.start()
    app.exec()
    socket.abort()
    return 1 if failed else 0
