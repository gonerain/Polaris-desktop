"""按日期管理的内存日程与一级子任务；提醒由应用级联动协调器负责。"""

import calendar
import re
from datetime import date
from itertools import count

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, Signal, Slot

_WEEKDAYS = "一二三四五六日"
_TIME_PATTERN = re.compile(r"^(\d{1,2})[:：](\d{1,2})$")


def clean_title(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def clean_time(value):
    """把时间规范成 HH:mm；空值表示全天，非法值返回 None。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return ""
    match = _TIME_PATTERN.fullmatch(value)
    if not match:
        return None
    hour, minute = (int(part) for part in match.groups())
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


class TaskEntry(QObject):
    titleChanged = Signal()
    timeChanged = Signal()
    doneChanged = Signal()
    subtasksChanged = Signal()
    subtaskProgressChanged = Signal()

    def __init__(self, title, ids, parent=None, *, is_subtask=False, time=""):
        super().__init__(parent)
        self._ids = ids
        self._id = next(ids)
        self._title = title
        self._time = time
        self._done = False
        self._subtasks = []
        self._is_subtask = is_subtask

    entryId = Property(int, lambda self: self._id, constant=True)
    title = Property(str, lambda self: self._title, notify=titleChanged)
    time = Property(str, lambda self: self._time, notify=timeChanged)
    done = Property(bool, lambda self: self._done, notify=doneChanged)
    subtasks = Property("QVariantList", lambda self: list(self._subtasks), notify=subtasksChanged)
    subtaskCount = Property(int, lambda self: len(self._subtasks), notify=subtasksChanged)
    completedSubtaskCount = Property(
        int,
        lambda self: sum(1 for subtask in self._subtasks if subtask.done),
        notify=subtaskProgressChanged,
    )

    @Slot(str, result=bool)
    def rename(self, title):
        title = clean_title(title)
        if not title:
            return False
        if title != self._title:
            self._title = title
            self.titleChanged.emit()
        return True

    @Slot(str, result=bool)
    def setTime(self, value):
        if self._is_subtask:
            return False
        cleaned = clean_time(value)
        if cleaned is None:
            return False
        if cleaned != self._time:
            self._time = cleaned
            self.timeChanged.emit()
        return True

    @Slot(bool, result=bool)
    def setDone(self, done):
        done = bool(done)
        if done != self._done:
            self._done = done
            self.doneChanged.emit()
        return True

    @Slot(str, result=QObject)
    def addSubtask(self, title):
        title = clean_title(title)
        if self._is_subtask or not title:
            return None
        entry = TaskEntry(title, self._ids, self, is_subtask=True)
        entry.doneChanged.connect(self._subtask_done_changed)
        self._subtasks.append(entry)
        self.subtasksChanged.emit()
        self.subtaskProgressChanged.emit()
        return entry

    @Slot(int, result=bool)
    def removeSubtask(self, entry_id):
        for index, entry in enumerate(self._subtasks):
            if entry.entryId == entry_id:
                self._subtasks.pop(index)
                self.subtasksChanged.emit()
                self.subtaskProgressChanged.emit()
                entry.deleteLater()
                return True
        return False

    def _subtask_done_changed(self):
        self.subtaskProgressChanged.emit()


class CalendarTaskStore(QObject):
    calendarChanged = Signal()
    selectedDateChanged = Signal()
    tasksChanged = Signal()
    summaryChanged = Signal()
    lastAddedTaskIdChanged = Signal()
    scheduleChanged = Signal()

    def __init__(self, parent=None, *, today=None):
        super().__init__(parent)
        self._today = today or date.today()
        self._selected = self._today
        self._ids = count(1)
        self._tasks_by_day = {}
        self._last_added_id = 0
        self._last_added_timer = QTimer(self)
        self._last_added_timer.setSingleShot(True)
        self._last_added_timer.setInterval(500)
        self._last_added_timer.timeout.connect(self._clear_last_added)

    selectedDate = Property(str, lambda self: self._selected.isoformat(), notify=selectedDateChanged)
    selectedDateLabel = Property(
        str, lambda self: f"{self._selected.month}月{self._selected.day}日", notify=selectedDateChanged
    )
    selectedWeekday = Property(
        str, lambda self: "周" + _WEEKDAYS[self._selected.weekday()], notify=selectedDateChanged
    )
    selectedDayNumber = Property(int, lambda self: self._selected.day, notify=selectedDateChanged)
    monthLabel = Property(str, lambda self: f"{self._selected.year}年{self._selected.month}月", notify=calendarChanged)
    tasks = Property("QVariantList", lambda self: self._sorted_tasks(self._entries_for(self._selected)),
                     notify=tasksChanged)
    taskCount = Property(int, lambda self: len(self._entries_for(self._selected)), notify=tasksChanged)
    completedCount = Property(
        int,
        lambda self: sum(1 for entry in self._entries_for(self._selected) if entry.done),
        notify=summaryChanged,
    )
    lastAddedTaskId = Property(int, lambda self: self._last_added_id, notify=lastAddedTaskIdChanged)

    @Property("QVariantList", notify=calendarChanged)
    def calendarCells(self):
        first = self._selected.replace(day=1)
        start = first.toordinal() - first.weekday()
        cells = []
        for offset in range(42):
            ordinal = start + offset
            day = date.fromordinal(ordinal) if date.min.toordinal() <= ordinal <= date.max.toordinal() else None
            entries = self._entries_for(day) if day is not None else ()
            cells.append({
                "date": day.isoformat() if day else "",
                "day": day.day if day else "",
                "inMonth": day is not None and day.month == first.month and day.year == first.year,
                "selected": day == self._selected,
                "today": day == self._today,
                "taskCount": len(entries),
                "openCount": sum(1 for entry in entries if not entry.done),
            })
        return cells

    def _entries_for(self, day):
        return self._tasks_by_day.get(day, ())

    def scheduled_entries(self):
        """供应用级联动读取全部日期；与当前选中的日期无关。"""
        for day, entries in self._tasks_by_day.items():
            for entry in entries:
                yield day, entry

    def _sorted_tasks(self, entries):
        return sorted(entries, key=lambda entry: (entry.time != "", entry.time))

    def _task_done_changed(self):
        self.summaryChanged.emit()
        self.calendarChanged.emit()
        self.scheduleChanged.emit()

    def _task_time_changed(self):
        self.tasksChanged.emit()
        self.scheduleChanged.emit()

    def _clear_last_added(self):
        if self._last_added_id:
            self._last_added_id = 0
            self.lastAddedTaskIdChanged.emit()

    @Slot(str, result=bool)
    def selectDate(self, value):
        try:
            selected = date.fromisoformat(value)
        except (ValueError, TypeError):
            return False
        if selected != self._selected:
            self._selected = selected
            if self._last_added_id:
                self._last_added_id = 0
                self.lastAddedTaskIdChanged.emit()
            self.selectedDateChanged.emit()
            self.calendarChanged.emit()
            self.tasksChanged.emit()
            self.summaryChanged.emit()
        return True

    @Slot(result=bool)
    def goToday(self):
        return self.selectDate(self._today.isoformat())

    @Slot(int, result=bool)
    def changeMonth(self, delta):
        month_index = self._selected.year * 12 + self._selected.month - 1 + delta
        year, month = divmod(month_index, 12)
        month += 1
        if not 1 <= year <= 9999:
            return False
        day = min(self._selected.day, calendar.monthrange(year, month)[1])
        return self.selectDate(date(year, month, day).isoformat())

    @Slot(str, result=bool)
    def isValidTime(self, value):
        return clean_time(value) is not None

    @Slot(str, str, result=QObject)
    def addTask(self, title, time_value=""):
        title = clean_title(title)
        cleaned_time = clean_time(time_value)
        if not title or cleaned_time is None:
            return None
        entry = TaskEntry(title, self._ids, self, time=cleaned_time)
        entry.doneChanged.connect(self._task_done_changed)
        entry.timeChanged.connect(self._task_time_changed)
        entry.titleChanged.connect(self.scheduleChanged.emit)
        self._tasks_by_day.setdefault(self._selected, []).append(entry)
        self._last_added_id = entry.entryId
        if QCoreApplication.instance() is not None:
            self._last_added_timer.start()
        self.lastAddedTaskIdChanged.emit()
        self.tasksChanged.emit()
        self.summaryChanged.emit()
        self.calendarChanged.emit()
        self.scheduleChanged.emit()
        return entry

    @Slot(int, result=bool)
    def removeTask(self, entry_id):
        entries = self._tasks_by_day.get(self._selected, [])
        for index, entry in enumerate(entries):
            if entry.entryId == entry_id:
                entries.pop(index)
                if self._last_added_id == entry_id:
                    self._last_added_id = 0
                    self.lastAddedTaskIdChanged.emit()
                self.tasksChanged.emit()
                self.summaryChanged.emit()
                self.calendarChanged.emit()
                self.scheduleChanged.emit()
                entry.deleteLater()
                return True
        return False
