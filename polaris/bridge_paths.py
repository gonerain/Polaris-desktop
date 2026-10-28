"""Platform-specific endpoint discovery. The wire protocol contains no OS paths."""
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

from PySide6.QtCore import QFileDevice, QIODevice, QSaveFile, QStandardPaths

MAX_FRAME = 65_536


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise OSError("桥目录不是普通目录")
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise OSError("桥目录须属于当前用户且权限为 0700")
    # Windows uses the user's profile ACL; the pipe itself uses UserAccessOption.
    return path


def endpoint_path(data_directory=None):
    if data_directory is None:
        location = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        if not location:
            raise OSError("无法确定用户数据目录")
        data_directory = Path(location)
    return Path(data_directory) / "bridge" / "endpoint.json"


def socket_address():
    if os.name == "nt":
        return "polaris-" + uuid.uuid4().hex, None
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime:
        try:
            info = Path(runtime).lstat()
            if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077:
                directory = private_directory(Path(runtime) / "polaris")
                address = str(directory / (uuid.uuid4().hex[:12] + ".sock"))
                if len(os.fsencode(address)) < 100:
                    return address, None
        except OSError:
            pass
    # A *random*, user-owned 0700 directory, not a predictable shared /tmp path.
    temporary = tempfile.TemporaryDirectory(prefix="polaris-ipc-")
    address = str(Path(temporary.name) / "bridge.sock")
    if len(os.fsencode(address)) >= 100:
        temporary.cleanup()
        raise OSError("本机套接字路径过长，请提供较短的私有运行目录")
    return address, temporary


def publish_endpoint(path, document):
    private_directory(path.parent)
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly):
        raise OSError(output.errorString())
    permissions = QFileDevice.ReadOwner | QFileDevice.WriteOwner
    if not output.setPermissions(permissions):
        output.cancelWriting()
        raise OSError(output.errorString())
    encoded = (json.dumps(document) + "\n").encode("utf8")
    if output.write(encoded) != len(encoded) or not output.commit():
        output.cancelWriting()
        raise OSError(output.errorString())


def read_endpoint(path):
    path = Path(path)
    if os.name != "nt":
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise OSError("端点文件须属于当前用户且不可被其他用户读取")
    with path.open("rb") as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise OSError("端点文件过大")
    document = json.loads(data)
    if (not isinstance(document, dict) or type(document.get("protocol")) is not int
            or document["protocol"] != 1 or not isinstance(document.get("address"), str)
            or not isinstance(document.get("token"), str) or len(document["token"]) != 64):
        raise OSError("端点文件格式或协议版本无效")
    address = document["address"]
    if ("\x00" in address or (os.name == "nt" and not address.startswith("\\\\.\\pipe\\"))
            or (os.name != "nt" and not Path(address).is_absolute())
            or any(char not in "0123456789abcdef" for char in document["token"])):
        raise OSError("端点必须是本机套接字或本机命名管道")
    return document
