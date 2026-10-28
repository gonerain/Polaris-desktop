"""Calendar-owned, explicitly authorized business operations for local clients."""
from datetime import date
from hashlib import sha256

from .component_api import ApiError, arguments, text
from .tasks import clean_time


def day(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ApiError("invalid_params", "date 必须为 YYYY-MM-DD 或 null（收集箱）") from None
    return value


def integer(value, name, minimum=1, maximum=2_147_483_647):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiError("invalid_params", f"{name} 必须为 {minimum}..{maximum} 的整数")
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise ApiError("invalid_params", f"{name} 必须是 boolean")
    return value


def page(args, maximum=100, default=20):
    return (integer(args.get("offset", 0), "offset", 0),
            integer(args.get("limit", default), "limit", 1, maximum))


def operation(name, description, access, parameters, returns, example):
    return {"name": name, "description": description, "access": access,
            "parameters": parameters, "returns": returns, "example": example}


_WRITE = "{applied,persisted,storageError,...}；applied=true勿重放，persisted=false请处理保存错误"
_ID = {"id": "主任务整数ID"}
_CHILD = {"taskId": "所属主任务整数ID", "id": "子任务整数ID"}
_NOTE = {"taskId": "主任务整数ID", "subtaskId?": "子任务整数ID；省略表示主任务笔记"}


class CalendarAPI:
    name = "日程"
    operations = [
        operation("calendar.status", "读取今天、主任务计数、保存状态及最近可撤销的主任务ID，不含笔记正文。", "read", {},
                  "{today,total,open,done,inbox,overdue,storageConfigured,storageError,undoTaskId}", {}),
        operation("task.list", "分页查询主任务摘要。省略date为全部，null为收集箱；日期范围含首尾、不含收集箱。query匹配标题和子任务标题，searchNotes=true才搜索笔记。保持存储顺序。", "read",
                  {"date?": "YYYY-MM-DD|null；不能与范围并用", "dateFrom?": "YYYY-MM-DD", "dateTo?": "YYYY-MM-DD",
                   "done?": "boolean", "important?": "boolean", "overdue?": "boolean；今天以前且未完成",
                   "query?": "字符串，最长2000", "searchNotes?": "boolean，默认false，须提供非空query",
                   "offset?": "integer>=0", "limit?": "1..100，默认20"},
                  "{total,tasks:[主任务摘要],nextOffset}；摘要不含笔记正文", {"date": None}),
        operation("task.get", "按ID读取主任务摘要及子任务计数；笔记用notes.get，子任务用subtask.list。", "read", _ID,
                  "{id,date,title,titleTruncated,time,done,important,subtaskCount,completedSubtaskCount,hasNotes}", {"id": 1}),
        operation("task.create", "创建主任务，默认收集箱；有时间须有日期，不改变界面浏览日期。", "write",
                  {"title": "非空字符串，最长2000", "date?": "YYYY-MM-DD|null，默认null", "time?": "HH:mm，默认空",
                   "important?": "boolean，默认false", "done?": "boolean，默认false"}, _WRITE + "，含task摘要", {"title": "整理资料"}),
        operation("task.update", "编辑主任务，至少提供一个可编辑字段；全部校验后一次保存。date=null默认清除原时间；显式非空time仍须有日期。", "write",
                  {**_ID, "title?": "非空字符串，最长2000", "date?": "YYYY-MM-DD|null", "time?": "HH:mm；空字符串清除",
                   "important?": "boolean", "done?": "boolean"}, _WRITE + "，含task摘要", {"id": 1, "important": True}),
        operation("task.reschedule", "改期；null移回收集箱并清除时间，保留子任务、笔记和完成状态。", "write",
                  {**_ID, "date": "YYYY-MM-DD|null"}, _WRITE + "，含task摘要", {"id": 1, "date": None}),
        operation("task.complete", "设置完成状态；不自动完成子任务。done=false取消完成。", "write",
                  {**_ID, "done?": "boolean，默认true"}, _WRITE + "，含task摘要", {"id": 1, "done": True}),
        operation("task.delete", "删除主任务及其子任务、笔记。覆盖上一次主任务撤销记录；仅本次运行可撤销。", "write",
                  _ID, _WRITE + "，含deleted任务摘要、undoTaskId", {"id": 1}),
        operation("task.restore", "撤销最近一次主任务删除；id须匹配undoTaskId，避免恢复其他任务。无跨重启回收站。", "write",
                  _ID, _WRITE + "，含task摘要", {"id": 1}),
        operation("task.reorder", "将主任务移到beforeId之前；两者须同一天或同为收集箱，不改变日期。", "write",
                  {**_ID, "beforeId": "目标主任务整数ID"}, _WRITE + "，含task摘要", {"id": 2, "beforeId": 1}),
        operation("task.move_overdue", "显式将全部过期未完成主任务移到今天，保留时间，一次保存；完成记录不移动。", "write", {},
                  _WRITE + "，含moved数量", {}),
        operation("day.review", "整理指定日期未完成任务。只处理明确列出的ID；keep保留、tomorrow次日、inbox收集箱并清时间。重复、失效或非当日ID拒绝整次操作。", "write",
                  {"date": "YYYY-MM-DD", "decisions": "最多100项 [{id:整数,action:keep|tomorrow|inbox}]"},
                  _WRITE + "，含moved数量", {"date": "2026-10-29", "decisions": [{"id": 1, "action": "inbox"}]}),
        operation("subtask.list", "分页读取一个主任务的一级子任务摘要，不含笔记。", "read",
                  {"taskId": "主任务整数ID", "done?": "boolean", "offset?": "integer>=0", "limit?": "1..100，默认20"},
                  "{total,subtasks:[{id,taskId,title,titleTruncated,done,hasNotes}],nextOffset}", {"taskId": 1}),
        operation("subtask.get", "读取子任务摘要；须同时提供所属主任务ID。", "read", _CHILD,
                  "子任务摘要，不含笔记", {"taskId": 1, "id": 2}),
        operation("subtask.create", "创建一级子任务；不能嵌套、单独安排日期、时间或设置重点。", "write",
                  {"taskId": "主任务整数ID", "title": "非空字符串，最长2000", "done?": "boolean，默认false"},
                  _WRITE + "，含subtask摘要", {"taskId": 1, "title": "查找资料"}),
        operation("subtask.update", "编辑子任务标题或完成状态，至少提供一个字段，不改变主任务完成状态。", "write",
                  {**_CHILD, "title?": "非空字符串，最长2000", "done?": "boolean"},
                  _WRITE + "，含subtask摘要", {"taskId": 1, "id": 2, "title": "核对资料"}),
        operation("subtask.complete", "设置子任务完成状态；不会自动完成主任务。", "write",
                  {**_CHILD, "done?": "boolean，默认true"}, _WRITE + "，含subtask摘要", {"taskId": 1, "id": 2}),
        operation("subtask.delete", "删除指定主任务下的子任务及笔记；与现有界面一致，不支持子任务撤销。", "write",
                  _CHILD, _WRITE + "，含deleted子任务摘要", {"taskId": 1, "id": 2}),
        operation("subtask.reorder", "将子任务移到beforeId之前；必须同属taskId。", "write",
                  {**_CHILD, "beforeId": "同一主任务下的子任务整数ID"},
                  _WRITE + "，含subtask摘要", {"taskId": 1, "id": 3, "beforeId": 2}),
        operation("notes.get", "显式按Unicode字符分段读取笔记；revision用于防止覆盖其他编辑。", "read",
                  {**_NOTE, "offset?": "integer>=0", "limit?": "1..4000，默认2000"},
                  "{taskId,subtaskId,offset,total,text,nextOffset,revision}", {"taskId": 1}),
        operation("notes.set", "替换笔记全文，空字符串清空。长笔记用notes.patch分段编辑；建议先读取并带expectedRevision。", "write",
                  {**_NOTE, "text": "字符串，最长8000字符", "expectedRevision?": "notes.get的revision，不匹配拒绝写入"},
                  _WRITE + "，含revision和length，不回传正文", {"taskId": 1, "text": "下一步：核对资料"}),
        operation("notes.patch", "按字符偏移替换一段笔记，支持长笔记；必须带expectedRevision，不匹配先重新读取。", "write",
                  {**_NOTE, "offset": "integer>=0", "deleteCount": "integer>=0", "text": "插入文本，最长8000字符",
                   "expectedRevision": "当前笔记revision"}, _WRITE + "，含revision和length，不回传正文",
                  {"taskId": 1, "offset": 0, "deleteCount": 0, "text": "下一步：", "expectedRevision": "从notes.get读取"}),
    ]

    def __init__(self, store):
        self.store = store

    @staticmethod
    def entry_summary(entry):
        return {"id": entry.entryId, "title": entry.title[:2000], "titleTruncated": len(entry.title) > 2000,
                "done": entry.done, "hasNotes": bool(entry.notes)}

    @classmethod
    def summary(cls, record):
        entry = record["task"]
        return {**cls.entry_summary(entry), "date": record["date"] or None,
                "time": entry.time, "important": entry.important, "subtaskCount": entry.subtaskCount,
                "completedSubtaskCount": entry.completedSubtaskCount}

    @classmethod
    def child_summary(cls, parent, child):
        return {**cls.entry_summary(child), "taskId": parent.entryId}

    def find(self, identity):
        integer(identity, "id")
        record = next((row for row in self.store.allEntries if row["task"].entryId == identity), None)
        if record is None:
            raise ApiError("not_found", "主任务不存在")
        return record

    @staticmethod
    def child(parent, identity):
        integer(identity, "subtask id")
        entry = next((entry for entry in parent.subtasks if entry.entryId == identity), None)
        if entry is None:
            raise ApiError("not_found", "该主任务下不存在此子任务")
        return entry

    @staticmethod
    def revision(entry):
        return sha256(entry.notes.encode("utf8")).hexdigest()

    def written(self, **result):
        return {"applied": True, "persisted": bool(self.store.storagePath) and not self.store.storageError,
                "storageError": self.store.storageError, **result}

    def call(self, name, args):
        definition = next((item for item in self.operations if item["name"] == name), None)
        if definition is None:
            raise ApiError("unknown_operation", "操作未登记")
        if definition["access"] == "write" and self.store.storageError:
            raise ApiError("storage_unavailable", "日程存在保存错误，请用户先处理后再修改")
        if name == "calendar.status":
            arguments(args, ())
            entries = self.store.allEntries
            done = sum(row["task"].done for row in entries)
            return {"today": self.store.todayDate, "total": len(entries), "done": done, "open": len(entries) - done,
                    "inbox": self.store.inboxCount, "overdue": self.store.overdueCount,
                    "storageConfigured": bool(self.store.storagePath), "storageError": self.store.storageError,
                    "undoTaskId": self.store.deleted_task_id()}
        if name == "task.list":
            return self.list_tasks(args)
        if name == "task.get":
            arguments(args, ("id",), ("id",))
            return self.summary(self.find(args["id"]))
        if name.startswith("notes."):
            return self.notes(name, args)
        if name.startswith("subtask."):
            return self.subtask(name, args)
        if name == "task.move_overdue":
            arguments(args, ())
            return self.written(moved=self.store.moveOverdueToToday())
        if name == "day.review":
            return self.review(args)
        if name == "task.create":
            arguments(args, ("title", "date", "time", "important", "done"), ("title",))
            changes = self.validate_changes(args, None)
            with self.store.batch_changes():
                entry = self.store.addTaskOnDate(changes["title"], changes["date"] or "", changes["time"])
                entry.setImportant(changes.get("important", False))
                entry.setDone(changes.get("done", False))
            return self.written(task=self.summary(self.find(entry.entryId)))
        if name in ("task.update", "task.reschedule", "task.complete"):
            allowed = {"task.update": ("id", "title", "date", "time", "important", "done"),
                       "task.reschedule": ("id", "date"), "task.complete": ("id", "done")}[name]
            arguments(args, allowed, ("id", "date") if name == "task.reschedule" else ("id",))
            record = self.find(args["id"])
            updates = {key: value for key, value in args.items() if key != "id"}
            if name == "task.complete":
                updates.setdefault("done", True)
            if not updates:
                raise ApiError("invalid_params", "至少提供一个可编辑字段")
            changes = self.validate_changes(updates, record)
            entry = record["task"]
            with self.store.batch_changes():
                if "date" in changes:
                    self.store.moveTask(entry.entryId, changes["date"] or "")
                self.edit_entry(entry, changes)
            return self.written(task=self.summary(self.find(entry.entryId)))
        if name == "task.delete":
            arguments(args, ("id",), ("id",))
            deleted = self.summary(self.find(args["id"]))
            self.store.removeTask(args["id"])
            return self.written(deleted=deleted, undoTaskId=self.store.deleted_task_id())
        if name == "task.restore":
            arguments(args, ("id",), ("id",))
            integer(args["id"], "id")
            if self.store.deleted_task_id() != args["id"]:
                raise ApiError("conflict", "该任务不是当前可撤销的最近删除任务")
            self.store.undoDelete()
            return self.written(task=self.summary(self.find(args["id"])))
        if name == "task.reorder":
            arguments(args, ("id", "beforeId"), ("id", "beforeId"))
            source, target = self.find(args["id"]), self.find(args["beforeId"])
            if source["date"] != target["date"]:
                raise ApiError("invalid_params", "排序任务必须属于同一天或同为收集箱")
            self.store.reorderTask(args["id"], args["beforeId"])
            return self.written(task=self.summary(self.find(args["id"])))
        raise ApiError("unknown_operation", "操作未登记")

    @staticmethod
    def validate_changes(args, record):
        changes = dict(args)
        if "title" in args:
            changes["title"] = text(args["title"], "title", 2000).strip()
        for key in ("done", "important"):
            if key in args:
                boolean(args[key], key)
        if "date" in args or record is None:
            changes["date"] = day(args.get("date"))
        target = changes.get("date", (record["date"] or None) if record else None)
        if "time" in args or record is None:
            value = args.get("time", "")
            when = clean_time(value) if isinstance(value, str) else None
            if when is None or (when and target is None):
                raise ApiError("invalid_params", "时间无效，或有时间但没有日期")
            changes["time"] = when
        return changes

    @staticmethod
    def edit_entry(entry, changes):
        for key, method in (("title", entry.rename), ("time", entry.setTime),
                            ("important", entry.setImportant), ("done", entry.setDone)):
            if key in changes:
                method(changes[key])

    def list_tasks(self, args):
        arguments(args, ("date", "dateFrom", "dateTo", "done", "important", "overdue", "query", "searchNotes", "offset", "limit"))
        offset, limit = page(args)
        target = day(args["date"]) if "date" in args else None
        if "date" in args and ("dateFrom" in args or "dateTo" in args):
            raise ApiError("invalid_params", "date不能与日期范围同时使用")
        bounds = {}
        for key in ("dateFrom", "dateTo"):
            if key in args:
                bounds[key] = day(args[key])
                if bounds[key] is None:
                    raise ApiError("invalid_params", "日期范围不能为null")
        if bounds.get("dateFrom", "") > bounds.get("dateTo", "9999-12-31"):
            raise ApiError("invalid_params", "日期范围起点不能晚于终点")
        for key in ("done", "important", "overdue", "searchNotes"):
            if key in args:
                boolean(args[key], key)
        query = text(args.get("query", ""), "query", 2000, empty=True).strip().casefold()
        if args.get("searchNotes") and not query:
            raise ApiError("invalid_params", "搜索笔记须提供非空query")
        records = []
        for row in self.store.allEntries:
            entry, when = row["task"], row["date"] or None
            if "date" in args and when != target:
                continue
            if bounds and (when is None or when < bounds.get("dateFrom", "") or when > bounds.get("dateTo", "9999-12-31")):
                continue
            if any(key in args and getattr(entry, key) != args[key] for key in ("done", "important")):
                continue
            if "overdue" in args and bool(row["overdue"]) != args["overdue"]:
                continue
            if query:
                entries = [entry, *entry.subtasks]
                if not any(query in item.title.casefold() or (args.get("searchNotes") and query in item.notes.casefold()) for item in entries):
                    continue
            records.append(row)
        return {"total": len(records), "tasks": [self.summary(row) for row in records[offset:offset + limit]],
                "nextOffset": offset + limit if offset + limit < len(records) else None}

    def subtask(self, name, args):
        allowed = {"subtask.list": ("taskId", "done", "offset", "limit"), "subtask.get": ("taskId", "id"),
                   "subtask.create": ("taskId", "title", "done"), "subtask.update": ("taskId", "id", "title", "done"),
                   "subtask.complete": ("taskId", "id", "done"), "subtask.delete": ("taskId", "id"),
                   "subtask.reorder": ("taskId", "id", "beforeId")}[name]
        required = ("taskId", "title") if name == "subtask.create" else ("taskId",) if name == "subtask.list" else ("taskId", "id")
        if name == "subtask.reorder":
            required += ("beforeId",)
        arguments(args, allowed, required)
        parent = self.find(args["taskId"])["task"]
        if name == "subtask.list":
            offset, limit = page(args)
            if "done" in args:
                boolean(args["done"], "done")
            children = [entry for entry in parent.subtasks if "done" not in args or entry.done == args["done"]]
            return {"total": len(children), "subtasks": [self.child_summary(parent, child) for child in children[offset:offset + limit]],
                    "nextOffset": offset + limit if offset + limit < len(children) else None}
        child = self.child(parent, args["id"]) if "id" in args else None
        if name == "subtask.get":
            return self.child_summary(parent, child)
        if name in ("subtask.create", "subtask.update", "subtask.complete"):
            updates = {key: value for key, value in args.items() if key in ("title", "done")}
            if name == "subtask.complete":
                updates.setdefault("done", True)
            if not updates:
                raise ApiError("invalid_params", "至少提供title或done")
            if "title" in updates:
                updates["title"] = text(updates["title"], "title", 2000).strip()
            if "done" in updates:
                boolean(updates["done"], "done")
            with self.store.batch_changes():
                if name == "subtask.create":
                    child = parent.addSubtask(updates["title"])
                self.edit_entry(child, updates)
        elif name == "subtask.delete":
            deleted = self.child_summary(parent, child)
            parent.removeSubtask(child.entryId)
            return self.written(deleted=deleted)
        elif name == "subtask.reorder":
            self.child(parent, args["beforeId"])
            parent.reorderSubtask(child.entryId, args["beforeId"])
        return self.written(subtask=self.child_summary(parent, child))

    def notes(self, name, args):
        allowed = {"notes.get": ("taskId", "subtaskId", "offset", "limit"),
                   "notes.set": ("taskId", "subtaskId", "text", "expectedRevision"),
                   "notes.patch": ("taskId", "subtaskId", "offset", "deleteCount", "text", "expectedRevision")}[name]
        required = ("taskId",) if name == "notes.get" else ("taskId", "text")
        if name == "notes.patch":
            required += ("offset", "deleteCount", "expectedRevision")
        arguments(args, allowed, required)
        parent = self.find(args["taskId"])["task"]
        entry = self.child(parent, args["subtaskId"]) if "subtaskId" in args else parent
        revision = self.revision(entry)
        if name == "notes.get":
            offset, limit = page(args, 4000, 2000)
            return {"taskId": parent.entryId, "subtaskId": entry.entryId if entry is not parent else None,
                    "offset": offset, "total": len(entry.notes), "text": entry.notes[offset:offset + limit],
                    "nextOffset": offset + limit if offset + limit < len(entry.notes) else None, "revision": revision}
        value = text(args["text"], "text", 8000, empty=True)
        if "expectedRevision" in args:
            expected = text(args["expectedRevision"], "expectedRevision", 64)
            if expected != revision:
                raise ApiError("conflict", "笔记已变化，请重新读取后编辑")
        if name == "notes.patch":
            offset = integer(args["offset"], "offset", 0, len(entry.notes))
            removed = integer(args["deleteCount"], "deleteCount", 0, len(entry.notes) - offset)
            value = entry.notes[:offset] + value + entry.notes[offset + removed:]
        entry.setNotes(value)
        return self.written(revision=self.revision(entry), length=len(entry.notes))

    def review(self, args):
        arguments(args, ("date", "decisions"), ("date", "decisions"))
        target = day(args["date"])
        if target is None or not isinstance(args["decisions"], list) or len(args["decisions"]) > 100:
            raise ApiError("invalid_params", "date须为日期；decisions须为最多100项的数组")
        decisions = []
        for item in args["decisions"]:
            arguments(item, ("id", "action"), ("id", "action"))
            identity = integer(item["id"], "id")
            action = item["action"]
            if not isinstance(action, str) or action not in ("keep", "tomorrow", "inbox"):
                raise ApiError("invalid_params", "action须为keep、tomorrow或inbox")
            decisions.append({"id": identity, "action": action})
        if not self.store.finishDay(target, decisions):
            raise ApiError("conflict", "任务已变化或整理目标无效，请重新查询")
        return self.written(moved=sum(item["action"] != "keep" for item in decisions))
