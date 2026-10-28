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
    notesChanged = Signal()
    importantChanged = Signal()
    subtasksChanged = Signal()
    subtaskProgressChanged = Signal()

    def __init__(self, title, ids, parent=None, *, is_subtask=False, time=""):
        super().__init__(parent)
        self._ids = ids
        self._id = next(ids)
        self._title = title
        self._time = time
        self._done = False
        self._notes = ""
        self._important = False
        self._subtasks = []
        self._is_subtask = is_subtask
        for signal in (self.titleChanged, self.timeChanged, self.doneChanged, self.subtasksChanged,
                       self.notesChanged, self.importantChanged):
            signal.connect(self.dataChanged.emit)

    entryId = Property(int, lambda self: self._id, constant=True)
    title = Property(str, lambda self: self._title, notify=titleChanged)
    time = Property(str, lambda self: self._time, notify=timeChanged)
    done = Property(bool, lambda self: self._done, notify=doneChanged)
    notes = Property(str, lambda self: self._notes, notify=notesChanged)
    important = Property(bool, lambda self: self._important, notify=importantChanged)
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

    @Slot(str, result=bool)
    def setNotes(self, value):
        if not isinstance(value, str):
            return False
        if value != self._notes:
            self._notes = value
            self.notesChanged.emit()
        return True

    @Slot(bool, result=bool)
    def setImportant(self, value):
        if self._is_subtask:
            return False
        if bool(value) != self._important:
            self._important = bool(value)
            self.importantChanged.emit()
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
    overdueCount = Property(int, lambda self: sum(not entry.done
        for day, entries in self._tasks_by_day.items() if day is not None and day < self._today for entry in entries),
        notify=agendaChanged)

    inboxCount = Property(int, lambda self: sum(not entry.done for entry in self._entries_for(None)),
                          notify=agendaChanged)

    def initialize_storage(self, path):
        if self._repository is not None or self._tasks_by_day:
            raise RuntimeError("存储必须在添加任务前初始化")
        self._repository = SnapshotRepository(path)
        try:
            document = self._repository.load()
            groups = [*document["days"].values(), document.get("inbox", [])]
            maximum = max((entry["id"] for entries in groups
                           for task in entries for entry in [task, *task.get("subtasks", [])]), default=0)
            self._ids = count(maximum + 1)
            for value, entries in document["days"].items():
                if document["version"] == 1:
                    entries = sorted(entries, key=lambda entry: (bool(entry.get("time")), entry.get("time", "")))
                self._tasks_by_day[date.fromisoformat(value)] = [self._restore(entry) for entry in entries]
            self._tasks_by_day[None] = [self._restore(entry) for entry in document.get("inbox", [])]
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
        entry._notes = record.get("notes", "")
        entry._important = record.get("important", False)
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
                "done": entry.done, "notes": entry.notes, "important": entry.important,
                "subtasks": [CalendarTaskStore._record(child) for child in entry.subtasks]}

    def _snapshot(self):
        return {"version": 2, "days": {day.isoformat(): [self._record(entry) for entry in entries]
                    for day, entries in self._tasks_by_day.items() if day is not None and entries},
                "inbox": [self._record(entry) for entry in self._entries_for(None)]}

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
        days = [None, *sorted(day for day in self._tasks_by_day if day is not None)]
        return [{"date": day.isoformat() if day else "", "task": entry,
                 "overdue": day is not None and day < self._today and not entry.done}
                for day in days for entry in self._entries_for(day)]

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
            target = date.fromisoformat(value) if value else None
            if target is not None and target.isoformat() != value:
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

    @Slot(result=int)
    def moveOverdueToToday(self):
        moved = []
        for day, entries in list(self._tasks_by_day.items()):
            if day is not None and day < self._today:
                moved.extend(entry for entry in entries if not entry.done)
                self._tasks_by_day[day] = [entry for entry in entries if entry.done]
        if moved:
            self._tasks_by_day.setdefault(self._today, []).extend(moved)
            self._notify_tasks()
        return len(moved)

    @Slot(str, result=str)
    def dateLabel(self, value):
        if not value:
            return "未安排日期"
        try:
            day = date.fromisoformat(value)
        except (ValueError, TypeError):
            return value
        delta = (day - self._today).days
        if delta in (-1, 0, 1):
            return {-1: "昨天", 0: "今天", 1: "明天"}[delta]
        prefix = f"{day.year}年" if day.year != self._today.year else ""
        return f"{prefix}{day.month}月{day.day}日 周{_WEEKDAYS[day.weekday()]}"

    @Slot(int, int, result=bool)
    def reorderToday(self, source_id, target_id):
        entries = self._tasks_by_day.get(self._today, [])
        pending = {entry.entryId: entry for entry in entries if not entry.done}
        if source_id not in pending or target_id not in pending:
            return False
        if source_id != target_id:
            source, target = pending[source_id], pending[target_id]
            destination = entries.index(target)
            entries.remove(source)
            entries.insert(destination, source)
            self._notify_tasks()
        return True

    @Slot(str, "QVariantList", result=bool)
    def finishDay(self, value, decisions):
        """Apply an explicit review in one save; omitted/completed/stale tasks stay put."""
        try:
            day = date.fromisoformat(value)
            if day.isoformat() != value:
                return False
        except (ValueError, TypeError):
            return False
        entries = self._tasks_by_day.get(day, [])
        current = {entry.entryId: entry for entry in entries if not entry.done}
        changes, seen = [], set()
        for decision in decisions:
            if not isinstance(decision, dict):
                return False
            identity, action = decision.get("id"), decision.get("action")
            if (type(identity) not in (int, float) or not 0 < identity <= 2_147_483_647
                    or int(identity) != identity or identity in seen
                    or action not in ("keep", "tomorrow", "inbox")):
                return False
            seen.add(identity)
            entry = current.get(identity)
            if entry is None or action == "keep":
                continue
            if action == "tomorrow" and day == date.max:
                return False
            target = day + timedelta(days=1) if action == "tomorrow" else None
            changes.append((entry, target))
        for entry, target in changes:
            entries.remove(entry)
            self._tasks_by_day.setdefault(target, []).append(entry)
        if changes:
            self._notify_tasks()
        return True

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
    tasks = Property("QVariantList", lambda self: list(self._entries_for(self._selected)),
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

    @Property("QVariantList", notify=calendarChanged)
    def weekCells(self):
        index = (self._selected.day - 1 + self._selected.replace(day=1).weekday()) // 7 * 7
        return self.calendarCells[index:index + 7]

    @Property(str, notify=calendarChanged)
    def weekLabel(self):
        start = date.fromordinal(self._selected.toordinal() - self._selected.weekday())
        end = date.fromordinal(min(date.max.toordinal(), start.toordinal() + 6))
        end_year = f"{end.year}年" if end.year != start.year else ""
        return f"{start.year}年{start.month}月{start.day}日 — {end_year}{end.month}月{end.day}日"

    def _entries_for(self, day):
        return self._tasks_by_day.get(day, ())

    def scheduled_entries(self):
        """供应用级联动读取全部日期；与当前选中的日期无关。"""
        for day, entries in self._tasks_by_day.items():
            if day is not None:
                for entry in entries:
                    yield day, entry

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
        return self._add_task(title, time_value, self._selected)

    @Slot(str, result=QObject)
    def addInboxTask(self, title):
        return self._add_task(title, "", None)

    def _add_task(self, title, time_value, day):
        title = clean_title(title)
        cleaned_time = clean_time(time_value)
        if not title or cleaned_time is None:
            return None
        entry = TaskEntry(title, self._ids, self, time=cleaned_time)
        self._connect_entry(entry)
        self._tasks_by_day.setdefault(day, []).append(entry)
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
