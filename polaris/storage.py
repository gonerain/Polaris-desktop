"""Versioned task snapshots with atomic replacement and a last-known-good backup."""
from datetime import date, datetime
import json
from pathlib import Path
import re
import shutil

from PySide6.QtCore import QSaveFile, QIODevice


class StorageError(Exception):
    pass


class SnapshotFormatError(StorageError):
    """The file was read, but its contents are invalid or unsupported."""


def validate_snapshot(document):
    if (not isinstance(document, dict) or type(document.get("version")) is not int
            or document["version"] != 1):
        raise SnapshotFormatError("不支持的数据版本")
    days = document.get("days")
    if not isinstance(days, dict):
        raise SnapshotFormatError("日程数据格式损坏")
    ids = set()

    def validate_entry(entry, subtask=False):
        if not isinstance(entry, dict):
            raise SnapshotFormatError("任务格式损坏")
        identity = entry.get("id")
        if type(identity) is not int or not 0 < identity <= 2_147_483_647 or identity in ids:
            raise SnapshotFormatError("任务编号无效或重复")
        ids.add(identity)
        if not isinstance(entry.get("title"), str) or not entry["title"].strip():
            raise SnapshotFormatError("任务名称无效")
        if type(entry.get("done")) is not bool:
            raise SnapshotFormatError("任务完成状态无效")
        time = entry.get("time", "")
        if not isinstance(time, str) or (time and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time)):
            raise SnapshotFormatError("任务时间无效")
        children = entry.get("subtasks", [])
        if not isinstance(children, list) or (subtask and (children or time)):
            raise SnapshotFormatError("子任务结构无效")
        for child in children:
            validate_entry(child, True)

    for day, entries in days.items():
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except (ValueError, TypeError):
            raise SnapshotFormatError("任务日期无效") from None
        if not isinstance(entries, list):
            raise SnapshotFormatError("日期列表损坏")
        for entry in entries:
            validate_entry(entry)
    return document


class SnapshotRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.backup = self.path.with_suffix(self.path.suffix + ".bak")
        self.blocked = False
        self.warning = ""
        self._recovered = False

    @staticmethod
    def read(path):
        try:
            return validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
        except OSError as error:
            raise StorageError(str(error)) from error
        except (ValueError, TypeError, RecursionError) as error:
            raise SnapshotFormatError(str(error)) from error

    def load(self):
        if not self.path.exists() and not self.backup.exists():
            return {"version": 1, "days": {}}
        try:
            return self.read(self.path)
        except StorageError:
            try:
                recovered = self.read(self.backup)
                # Preserve damaged input before allowing any subsequent overwrite.
                if self.path.exists():
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                    shutil.copyfile(self.path, self.path.with_name(f"tasks.corrupt-{stamp}.json"))
                self._recovered = True
                self.warning = "主文件异常，已从上次备份恢复；损坏文件已保留"
                return recovered
            except (StorageError, OSError) as error:
                self.blocked = True
                raise StorageError("日程文件与备份无法读取，已停止写入以保护原文件") from error

    @staticmethod
    def atomic_write(path, data):
        output = QSaveFile(str(path))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise StorageError(output.errorString())
        if output.write(data) != len(data):
            output.cancelWriting()
            raise StorageError(output.errorString())
        if not output.commit():
            raise StorageError(output.errorString())

    def save(self, document):
        if self.blocked:
            raise StorageError("原文件不可读，已停止自动保存；请先备份并修复数据文件")
        validate_snapshot(document)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    previous = self.read(self.path)
                except SnapshotFormatError as error:
                    if not self._recovered:
                        self.blocked = True
                        raise StorageError("文件在运行中损坏，已停止写入以保护原文件") from error
                    # load() already preserved the damaged file during recovery.
                    previous = None
                if previous is not None:
                    self.atomic_write(self.backup, self.encode(previous))
            self.atomic_write(self.path, self.encode(document))
            self._recovered = False
        except OSError as error:
            raise StorageError(str(error)) from error

    @staticmethod
    def encode(document):
        return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
