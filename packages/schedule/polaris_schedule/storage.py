"""Local versioned snapshots with atomic replacement and preserved recovery input."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4


class StorageError(Exception):
    pass


class SnapshotRepository:
    def __init__(self, path, validate):
        self.path = Path(path)
        self.backup = self.path.with_suffix(self.path.suffix + '.bak')
        self.validate = validate
        self.notice = ''
        self.blocked = False
        self.recovered = False

    def read(self, path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            self.validate(value)
            return value
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise StorageError(f'无法读取日程文件：{error}') from error

    @contextmanager
    def _file_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + '.lock')
        with lock_path.open('a+b') as lock:
            if os.name == 'nt':
                import msvcrt
                # Windows can lock beyond EOF. Writing before acquiring the
                # lock races another process and can fail with access denied.
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _revision(self):
        def content(path):
            try:
                return path.read_bytes()
            except FileNotFoundError:
                return None
        return content(self.path)

    def load(self):
        try:
            with self._file_lock():
                revision = self._revision()
                value = self._load()
                if revision != self._revision():
                    raise StorageError('读取时日程文件发生变化，请重新打开日程')
                self._expected = revision
                return value
        except OSError as error:
            raise StorageError(f'无法读取日程文件：{error}') from error

    def _load(self):
        if not self.path.exists() and not self.backup.exists():
            return {'version': 1, 'tasks': []}
        try:
            return self.read(self.path)
        except StorageError as primary:
            # Future formats must never be silently replaced by an older backup.
            try:
                raw = json.loads(self.path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raw = None
            if isinstance(raw, dict) and raw.get('version') != 1:
                self.blocked = True
                raise StorageError('不支持的日程数据版本，已停止写入') from primary
            try:
                value = self.read(self.backup)
                if self.path.exists():
                    preserved = self.path.with_name(self.path.name + '.corrupt-' + uuid4().hex)
                    preserved.write_bytes(self.path.read_bytes())
                self.recovered = True
                self.notice = '已从上一份备份恢复，异常原文件已保留'
                return value
            except (OSError, StorageError) as error:
                self.blocked = True
                raise StorageError('日程文件与备份无法读取，原文件保持不变') from error

    @staticmethod
    def atomic_write(path, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name, delete=False) as output:
                temporary = output.name
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, value):
        if self.blocked:
            raise StorageError('日程文件不可读，已停止写入')
        self.validate(value)
        try:
            with self._file_lock():
                if self._revision() != self._expected:
                    raise StorageError('日程文件已被其他窗口或程序修改，请重新打开日程后重试')
                if self.path.exists() and not self.recovered:
                    previous = self.read(self.path)
                    self.atomic_write(self.backup, self.encode(previous))
                encoded = self.encode(value)
                self.atomic_write(self.path, encoded)
                self.recovered = False
                self._expected = encoded
        except (OSError, StorageError) as error:
            raise StorageError(f'日程保存失败：{error}') from error

    @staticmethod
    def encode(value):
        return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
