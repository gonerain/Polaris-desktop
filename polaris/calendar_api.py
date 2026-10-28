"""Calendar-owned operations; transport and Agent UI know nothing about tasks."""
from datetime import date
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


class CalendarAPI:
    name = "日程"
    operations = [
        {"name": "task.list", "description": "查询主任务摘要，不自动读取笔记。省略 date 查询全部；null 只查收集箱。",
         "access": "read", "parameters": {"date?": "YYYY-MM-DD|null", "done?": "boolean", "offset?": "integer>=0", "limit?": "1..100，默认20"},
         "returns": "{total,tasks:[{id,date,title,time,done,important}],nextOffset}", "example": {"date": None}},
        {"name": "task.create", "description": "创建主任务；默认进入收集箱。有时间必须同时指定日期。",
         "access": "write", "parameters": {"title": "非空字符串，最长2000", "date?": "YYYY-MM-DD|null，默认null", "time?": "HH:mm，默认空"},
         "returns": "{applied,persisted,task,storageError}；applied=true 不要重复创建，即使 persisted=false", "example": {"title": "整理资料", "date": None}},
        {"name": "task.reschedule", "description": "移动主任务日期，不改变界面选中日期；null 移回收集箱。",
         "access": "write", "parameters": {"id": "主任务整数ID", "date": "YYYY-MM-DD|null"},
         "returns": "{applied,persisted,task,storageError}", "example": {"id": 1, "date": None}},
        {"name": "task.complete", "description": "设置主任务完成状态；可用 done=false 取消完成。",
         "access": "write", "parameters": {"id": "主任务整数ID", "done?": "boolean，默认true"},
         "returns": "{applied,persisted,task,storageError}", "example": {"id": 1, "done": True}},
    ]

    def __init__(self, store):
        self.store = store

    @staticmethod
    def summary(record):
        entry = record["task"]
        return {"id": entry.entryId, "date": record["date"] or None,
                "title": entry.title[:2000], "time": entry.time, "done": entry.done, "important": entry.important}

    def find(self, identity):
        if type(identity) is not int or not 0 < identity <= 2_147_483_647:
            raise ApiError("invalid_params", "id 必须是主任务整数ID")
        record = next((row for row in self.store.allEntries if row["task"].entryId == identity), None)
        if record is None:
            raise ApiError("not_found", "主任务不存在")
        return record

    def call(self, operation, args):
        if operation == "task.list":
            arguments(args, ("date", "done", "offset", "limit"))
            target = day(args["date"]) if "date" in args else None
            offset, limit = args.get("offset", 0), args.get("limit", 20)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
                raise ApiError("invalid_params", "offset / limit 无效")
            if "done" in args and type(args["done"]) is not bool:
                raise ApiError("invalid_params", "done 必须是 boolean")
            records = [row for row in self.store.allEntries
                       if ("date" not in args or (row["date"] or None) == target)
                       and ("done" not in args or row["task"].done == args["done"])]
            return {"total": len(records), "tasks": [self.summary(row) for row in records[offset:offset + limit]],
                    "nextOffset": offset + limit if offset + limit < len(records) else None}
        if self.store.storageError:
            raise ApiError("storage_unavailable", "日程存在保存错误，请用户先处理后再修改")
        if operation == "task.create":
            arguments(args, ("title", "date", "time"), ("title",))
            title = text(args["title"], "title", 2000)
            target, when = day(args.get("date")), args.get("time", "")
            if not isinstance(when, str) or clean_time(when) is None or (when and target is None):
                raise ApiError("invalid_params", "时间无效，或有时间但没有日期")
            entry = self.store.addTaskOnDate(title, target or "", when)
            if entry is None:
                raise ApiError("invalid_params", "无法创建任务")
            identity = entry.entryId
        elif operation == "task.reschedule":
            arguments(args, ("id", "date"), ("id", "date"))
            identity = self.find(args["id"])["task"].entryId
            target = day(args["date"])
            self.store.moveTask(identity, target or "")
        elif operation == "task.complete":
            arguments(args, ("id", "done"), ("id",))
            record = self.find(args["id"])
            done = args.get("done", True)
            if type(done) is not bool:
                raise ApiError("invalid_params", "done 必须是 boolean")
            identity = record["task"].entryId
            record["task"].setDone(done)
        else:
            raise ApiError("unknown_operation", "操作未登记")
        return {"applied": True, "persisted": bool(self.store.storagePath) and not self.store.storageError,
                "task": self.summary(self.find(identity)), "storageError": self.store.storageError}
