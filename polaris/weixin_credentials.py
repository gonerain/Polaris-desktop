"""Local-only account storage. Windows DPAPI; other platforms stay in memory."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys

from PySide6.QtCore import QIODevice, QSaveFile


def protect(data, *, decrypt=False):
    if sys.platform != "win32":
        raise OSError("此平台暂不保存微信凭证，本次登录仅保留在内存")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Windows 无法加解密微信凭证")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class CredentialStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None

    def load(self):
        if self.path is None or not self.path.exists():
            return None
        if self.path.stat().st_size > 262144:
            raise ValueError("凭证文件过大")
        result = json.loads(protect(self.path.read_bytes(), decrypt=True))
        if not isinstance(result, dict) or result.get("version") != 1:
            raise ValueError("凭证格式不支持")
        return result

    def save(self, account):
        if self.path is None:
            return False
        data = protect(json.dumps({"version": 1, **account}, ensure_ascii=False).encode("utf8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        output = QSaveFile(str(self.path))
        if not output.open(QIODevice.WriteOnly):
            raise OSError("无法写入微信凭证")
        if output.write(data) != len(data):
            output.cancelWriting()
            raise OSError("无法完整写入微信凭证")
        if not output.commit():
            raise OSError("无法保存微信凭证")
        return True

    def clear(self):
        if self.path is not None:
            self.path.unlink(missing_ok=True)
