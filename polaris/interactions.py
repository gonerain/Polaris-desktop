"""应用级组件联动：读取日程状态，发出与展示方式无关的通知。"""

from datetime import datetime, timedelta
from math import ceil

from PySide6.QtCore import QObject, QTimer, Signal


class InteractionCoordinator(QObject):
    notification = Signal(str, int, str)  # 类型、来源任务 ID、文案

    def __init__(self, parent=None, *, clock=None):
        super().__init__(parent)
        self._clock = clock or datetime.now
        self._store = None
        self._sent = set()
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.check)

    def attach(self, store):
        if self._store is not None:
            raise RuntimeError("联动协调器已绑定日程组件")
        self._store = store
        store.scheduleChanged.connect(self.check)
        self._timer.start()
        self.check()

    def check(self):
        if self._store is None:
            return
        now = self._clock()
        scheduled = []
        valid_keys = set()
        for day, task in self._store.scheduled_entries():
            if not task.time:
                continue
            hour, minute = map(int, task.time.split(":"))
            due = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
            key = (task.entryId, due)
            valid_keys.add(key)
            if not task.done and due - timedelta(minutes=10) <= now < due and key not in self._sent:
                minutes_left = ceil((due - now).total_seconds() / 60)
                scheduled.append((due, task.entryId, task.title, key, minutes_left))
        # 保留仍存在的任务记录：完成再取消完成、切换日期都不会重复提示。
        self._sent.intersection_update(valid_keys)
        for _, entry_id, title, key, minutes_left in sorted(scheduled):
            self._sent.add(key)
            self.notification.emit("task.upcoming", entry_id, f"{minutes_left} 分钟后 · {title}")
