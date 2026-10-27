"""Calendar tasks, shared view state, safe persistence and one-step delete recovery."""

import calendar
import re
from datetime import date, timedelta
from itertools import count

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, Signal, Slot, QUrl

from .storage import SnapshotRepository, StorageError

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
    dataChanged = Signal()
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
        for signal in (self.titleChanged, self.timeChanged, self.doneChanged, self.subtasksChanged):
            signal.connect(self.dataChanged.emit)

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
        entry.dataChanged.connect(self.dataChanged.emit)
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
    agendaChanged = Signal()
    contentChanged = Signal()
    undoChanged = Signal()
    storageChanged = Signal()

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
        self._repository = None
        self._storage_error = ""
        self._storage_notice = ""
        self._undo = None
        self._today_override = today is not None
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(30_000)
        self._day_timer.timeout.connect(self.refreshToday)
        if QCoreApplication.instance() is not None:
            self._day_timer.start()
        self.contentChanged.connect(self._save)

    storageError = Property(str, lambda self: self._storage_error, notify=storageChanged)
    storageNotice = Property(str, lambda self: self._storage_notice, notify=storageChanged)
    storagePath = Property(str, lambda self: str(self._repository.path) if self._repository else "",
                           notify=storageChanged)
    storageDirectoryUrl = Property(str, lambda self: QUrl.fromLocalFile(str(self._repository.path.parent)).toString()
                                   if self._repository else "", notify=storageChanged)
    canUndoDelete = Property(bool, lambda self: self._undo is not None, notify=undoChanged)
    allEntries = Property("QVariantList", lambda self: self._all_entries(), notify=agendaChanged)

    def initialize_storage(self, path):
        if self._repository is not None or self._tasks_by_day:
            raise RuntimeError("存储必须在添加任务前初始化")
        self._repository = SnapshotRepository(path)
        try:
            document = self._repository.load()
            maximum = max((entry["id"] for entries in document["days"].values()
                           for task in entries for entry in [task, *task.get("subtasks", [])]), default=0)
            self._ids = count(maximum + 1)
            for value, entries in document["days"].items():
                self._tasks_by_day[date.fromisoformat(value)] = [self._restore(entry) for entry in entries]
            self._storage_notice = self._repository.warning
        except StorageError as error:
            self._storage_error = str(error)
        self.storageChanged.emit()
        self.tasksChanged.emit()
        self.summaryChanged.emit()
        self.calendarChanged.emit()
        self.scheduleChanged.emit()
        # View refresh is separate from content changes: never save on load.
        self.agendaChanged.emit()

    def _restore(self, record, parent=None, subtask=False):
        entry = TaskEntry(record["title"], count(record["id"]), parent or self,
                          is_subtask=subtask, time=record.get("time", ""))
        entry._ids = self._ids
        entry._done = record["done"]
        for child_record in record.get("subtasks", []):
            child = self._restore(child_record, entry, True)
            child.doneChanged.connect(entry._subtask_done_changed)
            child.dataChanged.connect(entry.dataChanged.emit)
            entry._subtasks.append(child)
        if not subtask:
            self._connect_entry(entry)
        return entry

    def _connect_entry(self, entry):
        entry.doneChanged.connect(self._task_done_changed)
        entry.timeChanged.connect(self._task_time_changed)
        entry.titleChanged.connect(self.scheduleChanged.emit)
        entry.dataChanged.connect(self.agendaChanged.emit)
        entry.dataChanged.connect(self.contentChanged.emit)

    @staticmethod
    def _record(entry):
        return {"id": entry.entryId, "title": entry.title, "time": entry.time,
                "done": entry.done, "subtasks": [CalendarTaskStore._record(child) for child in entry.subtasks]}

    def _snapshot(self):
        return {"version": 1, "days": {day.isoformat(): [self._record(entry) for entry in entries]
                                       for day, entries in self._tasks_by_day.items() if entries}}

    @Slot(result=bool)
    def retrySave(self):
        return self._save()

    def _save(self):
        if self._repository is None:
            return True
        try:
            self._repository.save(self._snapshot())
            self._storage_error = ""
        except StorageError as error:
            self._storage_error = "保存失败：" + str(error)
            self.storageChanged.emit()
            return False
        self.storageChanged.emit()
        return True

    def _all_entries(self):
        return [{"date": day.isoformat(), "task": entry, "overdue": day < self._today and not entry.done}
                for day in sorted(self._tasks_by_day)
                for entry in self._sorted_tasks(self._tasks_by_day[day])]

    @Slot()
    def refreshToday(self):
        if self._today_override:
            return
        current = date.today()
        if current == self._today:
            return
        followed_today = self._selected == self._today
        self._today = current
        if followed_today:
            self.selectDate(current.isoformat())
        else:
            self.calendarChanged.emit()
        # Refresh date-dependent overdues without writing unchanged data.
        self.agendaChanged.emit()

    def _notify_tasks(self):
        self.tasksChanged.emit()
        self.summaryChanged.emit()
        self.calendarChanged.emit()
        self.scheduleChanged.emit()
        self.agendaChanged.emit()
        self.contentChanged.emit()

    @Slot(int, str, result=bool)
    def moveTask(self, entry_id, value):
        try:
            target = date.fromisoformat(value)
            if target.isoformat() != value:
                return False
        except (ValueError, TypeError):
            return False
        for day, entries in list(self._tasks_by_day.items()):
            for entry in list(entries):
                if entry.entryId == entry_id:
                    if day != target:
                        entries.remove(entry)
                        self._tasks_by_day.setdefault(target, []).append(entry)
                        self._notify_tasks()
                    return True
        return False

    @Slot(result=bool)
    def undoDelete(self):
        if self._undo is None:
            return False
        day, index, entry = self._undo
        self._undo = None
        self._tasks_by_day.setdefault(day, []).insert(index, entry)
        self.undoChanged.emit()
        self._notify_tasks()
        return True

    todayDate = Property(str, lambda self: self._today.isoformat(), notify=calendarChanged)
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

    @Slot(int, result=bool)
    def changeDay(self, delta):
        try:
            return self.selectDate((self._selected + timedelta(days=delta)).isoformat())
        except (OverflowError, ValueError):
            return False

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
        self._connect_entry(entry)
        self._tasks_by_day.setdefault(self._selected, []).append(entry)
        self._last_added_id = entry.entryId
        if QCoreApplication.instance() is not None:
            self._last_added_timer.start()
        self.lastAddedTaskIdChanged.emit()
        self.tasksChanged.emit()
        self.summaryChanged.emit()
        self.calendarChanged.emit()
        self.scheduleChanged.emit()
        self.agendaChanged.emit()
        self.contentChanged.emit()
        return entry

    @Slot(int, result=bool)
    def removeTask(self, entry_id):
        for day, entries in self._tasks_by_day.items():
            for index, entry in enumerate(entries):
                if entry.entryId == entry_id:
                    if self._undo is not None:
                        self._undo[2].deleteLater()
                    self._undo = (day, index, entry)
                    entries.pop(index)
                    if self._last_added_id == entry_id:
                        self._last_added_id = 0
                        self.lastAddedTaskIdChanged.emit()
                    self.undoChanged.emit()
                    self._notify_tasks()
                    return True
        return False
