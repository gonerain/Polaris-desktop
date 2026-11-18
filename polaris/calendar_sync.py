"""Calendar-owned Qt controller. Network work never touches live Qt task objects."""
import json
from pathlib import Path
from threading import Event
from uuid import uuid4, UUID

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from . import onedrive_api
from .storage import SnapshotRepository, StorageError
from .sync_merge import SyncError, capture, digest, materialize


class Job(QThread):
    progress = Signal(object)
    completed = Signal(object)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.cancelled = Event()
        self.action = action

    def run(self):
        try:
            result = self.action(self.cancelled, self.progress.emit)
            self.completed.emit({"result": result})
        except Exception as error:
            # Never expose request bodies, signed download URLs or tokens.
            message = str(error) if isinstance(error, StorageError) else "同步异常，未覆盖本地数据；请重试"
            self.completed.emit({"error": message})


class CalendarSync(QObject):
    changed = Signal()

    def __init__(self, store, path, parent=None):
        super().__init__(parent)
        self._store = store
        self._path = Path(path)
        self._client_id = ""
        self._device = str(uuid4())
        self._sequence = 0
        self._token = None
        self._job = None
        self._status = "未连接；云端为明文日程，仅在你登录后同步"
        self._code = self._url = ""
        self._auto = False
        self._blocked = False
        self._closed = False
        try:
            if self._path.exists():
                config = json.loads(self._path.read_text(encoding="utf8"))
                if config.get("version") != 1:
                    raise ValueError("Unsupported config")
                self._device = str(UUID(config["device"]))
                self._sequence = config.get("sequence", 0)
                if type(self._sequence) is not int or not 0 <= self._sequence < 10**19:
                    raise ValueError("Invalid sequence")
                self._client_id = str(UUID(config["clientId"])) if config.get("clientId") else ""
                self._auto = config.get("auto", False) is True
        except (OSError, ValueError, TypeError, KeyError):
            self._blocked = True
            self._status = "同步配置损坏；请备份并修复 onedrive-config.json，未启动同步"
        self._timer = QTimer(self)
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self._automatic)
        self._timer.start()
        store._sync = self
        store.syncChanged.emit()

    busy = Property(bool, lambda self: self._job is not None, notify=changed)
    connected = Property(bool, lambda self: self._token is not None, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    userCode = Property(str, lambda self: self._code, notify=changed)
    loginUrl = Property(str, lambda self: self._url, notify=changed)
    clientId = Property(str, lambda self: self._client_id, notify=changed)
    autoSync = Property(bool, lambda self: self._auto, notify=changed)

    def _save_config(self):
        if self._blocked:
            raise SyncError("同步配置不可写，请先修复")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        SnapshotRepository.atomic_write(self._path, SnapshotRepository.encode(
            {"version": 1, "device": self._device, "sequence": self._sequence,
             "clientId": self._client_id, "auto": self._auto}))

    @Slot(bool)
    def setAutoSync(self, enabled):
        old = self._auto
        try:
            self._auto = bool(enabled)
            self._save_config()
        except (StorageError, OSError) as error:
            self._auto = old
            self._status = str(error)
        self.changed.emit()

    def _automatic(self):
        if self._auto and self._token and not self.busy:
            self.syncNow()

    def _start(self, action, finish):
        job = Job(action, self)
        self._job = job
        outcome = {}
        job.progress.connect(self._progress)
        job.completed.connect(lambda value: outcome.update(value))

        def done():
            self._job = None
            if not self._closed:
                self._code = self._url = ""
                if job.cancelled.is_set():
                    self._status = "已取消；云端可能已有检查点，下次同步会安全合并"
                elif "error" in outcome:
                    self._status = outcome["error"]
                elif "result" in outcome:
                    try:
                        finish(outcome["result"])
                    except (StorageError, OSError) as error:
                        self._status = str(error)
                self.changed.emit()
            job.deleteLater()

        job.finished.connect(done)
        job.start()
        self.changed.emit()

    @Slot(object)
    def _progress(self, value):
        if self._closed or self._job is None or self._job.cancelled.is_set():
            return
        if "token" in value:
            self._token = value["token"]
        else:
            self._code, self._url = value["code"], value["url"]
            self._status = "在微软页面输入登录码；此程序不索取微软密码"
        self.changed.emit()

    @Slot(str)
    def connectAccount(self, client_id):
        if self.busy or self._closed or self._blocked:
            return
        try:
            self._client_id = str(UUID(client_id.strip()))
            self._save_config()
        except (ValueError, OSError, StorageError):
            self._status = "请填写有效的微软应用 Client ID，并确保配置目录可写"
            self.changed.emit()
            return
        self._status = "正在申请微软设备登录码…"

        def finish(token):
            self._token = token
            self._status = "已登录（凭证仅本次运行有效），可点击立即同步"

        client = self._client_id
        self._start(lambda cancel, notify: onedrive_api.login(client, cancel, notify), finish)

    @Slot()
    def syncNow(self):
        if self.busy or not self._token or self._closed:
            return
        try:
            snapshot = self._store.export_sync_snapshot()
            state = capture(snapshot, snapshot["syncState"], self._device)
            # Persist UUIDs and causality BEFORE publishing any cloud packet.
            self._store.checkpoint_sync(state)
            original = digest(self._store.export_sync_snapshot())
            self._sequence += 1
            self._save_config()
        except (StorageError, OSError) as error:
            self._status = str(error)
            self.changed.emit()
            return
        self._status = "正在与 OneDrive 合并日程…"
        client, token = self._client_id, dict(self._token)
        device, sequence = self._device, self._sequence

        def action(cancel, notify):
            fresh = onedrive_api.refresh(client, token)
            notify({"token": fresh})
            return onedrive_api.synchronize(state, fresh, cancel, device, sequence)

        def finish(result):
            merged, conflicts = result
            current = self._store.export_sync_snapshot()
            if digest(current) != original:
                self._status = "同步期间有本地编辑，未替换界面数据；请再次同步合并"
                return
            if merged != current["syncState"]:
                self._store.apply_sync_snapshot(materialize(merged, current))
            self._status = (f"已同步；{conflicts} 处并发修改已保留副本（删除/编辑冲突保留编辑）"
                            if conflicts else "已同步到 OneDrive")

        self._start(action, finish)

    @Slot()
    def cancel(self):
        if self._job:
            self._job.cancelled.set()
            self._status = "正在取消，请等待当前网络请求结束…"
            self.changed.emit()

    @Slot()
    def disconnectAccount(self):
        if self.busy:
            return
        self._token = None
        self._code = self._url = ""
        self._status = "已断开；云端文件保留。撤销平台授权请前往微软账号权限页面"
        self.changed.emit()

    def shutdown(self):
        self._closed = True
        self._timer.stop()
        self._token = None
        if self._job:
            self._job.cancelled.set()
            # Network calls have a finite timeout. Do not destroy a running QThread.
            self._job.wait()
