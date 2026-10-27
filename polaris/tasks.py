"""按日期管理的内存任务与一级子任务，不包含持久化或提醒。"""

import calendar
from datetime import date
from itertools import count

from PySide6.QtCore import QObject, Property, Signal, Slot


def clean_title(value) -> str:
    return value.strip() if isinstance(value, str) else ""


class TaskEntry(QObject):
    titleChanged = Signal()
    subtasksChanged = Signal()

    def __init__(self, title, ids, parent=None, *, is_subtask=False):
        super().__init__(parent)
        self._ids = ids
        self._id = next(ids)
        self._title = title
        self._subtasks = []
        self._is_subtask = is_subtask

    entryId = Property(int, lambda self: self._id, constant=True)
    title = Property(str, lambda self: self._title, notify=titleChanged)
    subtasks = Property("QVariantList", lambda self: list(self._subtasks), notify=subtasksChanged)

    @Slot(str, result=bool)
    def rename(self, title):
        title = clean_title(title)
        if not title:
            return False
        if title != self._title:
            self._title = title
            self.titleChanged.emit()
        return True

    @Slot(str, result=QObject)
    def addSubtask(self, title):
        title = clean_title(title)
        if self._is_subtask or not title:
            return None
        entry = TaskEntry(title, self._ids, self, is_subtask=True)
        self._subtasks.append(entry)
        self.subtasksChanged.emit()
        return entry

    @Slot(int, result=bool)
    def removeSubtask(self, entry_id):
        for index, entry in enumerate(self._subtasks):
            if entry.entryId == entry_id:
                self._subtasks.pop(index)
                self.subtasksChanged.emit()
                entry.deleteLater()
                return True
        return False


class CalendarTaskStore(QObject):
    calendarChanged = Signal()
    selectedDateChanged = Signal()
    tasksChanged = Signal()

    def __init__(self, parent=None, *, today=None):
        super().__init__(parent)
        self._today = today or date.today()
        self._selected = self._today
        self._ids = count(1)
        self._tasks_by_day = {}

    selectedDate = Property(str, lambda self: self._selected.isoformat(), notify=selectedDateChanged)
    monthLabel = Property(str, lambda self: f"{self._selected.year}年{self._selected.month}月", notify=calendarChanged)
    tasks = Property("QVariantList", lambda self: list(self._tasks_by_day.get(self._selected, [])), notify=tasksChanged)

    @Property("QVariantList", notify=calendarChanged)
    def calendarCells(self):
        first = self._selected.replace(day=1)
        start = first.toordinal() - first.weekday()
        cells = []
        for offset in range(42):
            ordinal = start + offset
            day = date.fromordinal(ordinal) if date.min.toordinal() <= ordinal <= date.max.toordinal() else None
            cells.append({
                "date": day.isoformat() if day else "",
                "day": day.day if day else "",
                "inMonth": day is not None and day.month == first.month and day.year == first.year,
                "selected": day == self._selected,
                "today": day == self._today,
            })
        return cells

    @Slot(str, result=bool)
    def selectDate(self, value):
        try:
            selected = date.fromisoformat(value)
        except (ValueError, TypeError):
            return False
        if selected != self._selected:
            self._selected = selected
            self.selectedDateChanged.emit()
            self.calendarChanged.emit()
            self.tasksChanged.emit()
        return True

    @Slot(int, result=bool)
    def changeMonth(self, delta):
        month_index = self._selected.year * 12 + self._selected.month - 1 + delta
        year, month = divmod(month_index, 12)
        month += 1
        if not 1 <= year <= 9999:
            return False
        day = min(self._selected.day, calendar.monthrange(year, month)[1])
        return self.selectDate(date(year, month, day).isoformat())

    @Slot(str, result=QObject)
    def addTask(self, title):
        title = clean_title(title)
        if not title:
            return None
        entry = TaskEntry(title, self._ids, self)
        self._tasks_by_day.setdefault(self._selected, []).append(entry)
        self.tasksChanged.emit()
        return entry

    @Slot(int, result=bool)
    def removeTask(self, entry_id):
        entries = self._tasks_by_day.get(self._selected, [])
        for index, entry in enumerate(entries):
            if entry.entryId == entry_id:
                entries.pop(index)
                self.tasksChanged.emit()
                entry.deleteLater()
                return True
        return False
