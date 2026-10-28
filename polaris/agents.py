"""Provider-neutral, ephemeral sessions and connection permissions."""
from collections import OrderedDict
from datetime import datetime
import json
import time

from PySide6.QtCore import QObject, Property, Signal, Slot
from .component_api import ApiError, arguments, text

OUTCOMES = {"ended": "本轮已结束", "failed": "本轮失败", "cancelled": "本轮已取消", "unknown": "本轮结束，结果未知"}


class AgentHub(QObject):
    name = "Agent"
    operations = [
        {"name": "session.list", "access": "read", "description": "查询已接入会话元数据，不含提示词或回复。",
         "parameters": {"offset?": "integer>=0", "limit?": "1..100，默认20"},
         "returns": "{total,sessions,nextOffset}", "example": {"limit": 20}},
        {"name": "result.list", "access": "read", "description": "最近十次结束结果，仅本次应用运行。",
         "parameters": {}, "returns": "{results,unreadCount}", "example": {}},
    ]
    changed = Signal()
    clientsChanged = Signal()
    completed = Signal(str)
    permissionRequested = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions = {}
        self._clients = {}
        self._finished = OrderedDict()
        self._results = []
        self._error = ""

    sessions = Property("QVariantList", lambda self: [dict(row) for row in sorted(
        self._sessions.values(), key=lambda row: (row["state"] == "running", row["updated"]), reverse=True)], notify=changed)
    clients = Property("QVariantList", lambda self: [dict(row) for row in self._clients.values()], notify=clientsChanged)
    results = Property("QVariantList", lambda self: [dict(row) for row in self._results], notify=changed)
    unreadCount = Property(int, lambda self: sum(row["unread"] for row in self._results), notify=changed)
    connectionError = Property(str, lambda self: self._error, notify=changed)

    def call(self, operation, args):
        if operation == "result.list":
            arguments(args, ())
            return {"results": self.results, "unreadCount": self.unreadCount}
        if operation != "session.list":
            raise ApiError("unknown_operation", "操作未登记")
        arguments(args, ("offset", "limit"))
        offset, limit = args.get("offset", 0), args.get("limit", 20)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ApiError("invalid_params", "offset / limit 无效")
        rows = self.sessions
        fields = ("instanceId", "sessionId", "source", "name", "project", "state", "runId", "outcome")
        return {"total": len(rows), "sessions": [{key: row[key] for key in fields} for row in rows[offset:offset + limit]],
                "nextOffset": offset + limit if offset + limit < len(rows) else None}

    def set_error(self, message):
        self._error = message
        self.changed.emit()

    def connect_client(self, instance, name):
        self._clients[instance] = {"instanceId": instance, "name": name, "grants": {}}
        self.clientsChanged.emit()
        self.changed.emit()

    def disconnect_client(self, instance):
        self._clients.pop(instance, None)
        self.clientsChanged.emit()
        for (owner, _), row in self._sessions.items():
            if owner == instance:
                row.update(state="disconnected", expires=time.monotonic() + 30)
        self.changed.emit()

    def snapshot(self, instance, data):
        arguments(data, ("sessionId", "source", "name", "project", "state", "runId", "outcome"),
                  ("sessionId", "source", "name", "project", "state"))
        sid = text(data["sessionId"], "sessionId")
        source = text(data["source"], "source", 64)
        name = text(data["name"], "name", 128)
        project = text(data["project"], "project", 4096, empty=True)
        state = data["state"]
        if state not in ("idle", "running"):
            raise ApiError("invalid_params", "快照状态只能是 idle / running")
        run = text(data.get("runId", ""), "runId", 128, empty=state == "idle")
        outcome = data.get("outcome", "")
        if outcome not in ("", *OUTCOMES):
            raise ApiError("invalid_params", "未知运行结果")
        key = instance, sid
        if state == "running" and (instance, sid, run) in self._finished:
            raise ApiError("invalid_state", "快照不得复用已经结束的 runId")
        if key not in self._sessions and len(self._sessions) >= 128:
            raise ApiError("limit_exceeded", "最多接入 128 个会话")
        self._sessions[key] = {"key": json.dumps(key), "instanceId": instance, "sessionId": sid,
                               "source": source, "name": name, "project": project, "state": state,
                               "runId": run, "outcome": outcome, "updated": time.monotonic(), "expires": 0}
        self.changed.emit()  # Snapshots never produce completion notifications.

    def event(self, instance, event, data):
        if event == "session.snapshot":
            self.snapshot(instance, data)
            return
        allowed = ("sessionId",) if event == "session.removed" else ("sessionId", "runId", "outcome")
        arguments(data, allowed, ("sessionId",))
        sid = text(data["sessionId"], "sessionId")
        key = instance, sid
        row = self._sessions.get(key)
        if event == "session.removed":
            self._sessions.pop(key, None)
            self.changed.emit()
            return
        if row is None:
            raise ApiError("unknown_session", "请先发送会话快照")
        run = text(data.get("runId"), "runId", 128)
        if event == "run.started":
            if (instance, sid, run) in self._finished:
                raise ApiError("invalid_state", "runId 必须在实例中唯一，不可重复使用")
            if row["state"] == "running" and row["runId"] != run:
                raise ApiError("invalid_state", "前一轮尚未结束")
            row.update(state="running", runId=run, outcome="", updated=time.monotonic())
            self.changed.emit()
        elif event == "run.ended":
            outcome = data.get("outcome")
            if outcome not in OUTCOMES:
                raise ApiError("invalid_params", "outcome 必须是 ended / failed / cancelled / unknown")
            identity = instance, sid, run
            if identity in self._finished:
                return
            if row["state"] != "running" or row["runId"] != run:
                raise ApiError("invalid_state", "结束事件不匹配当前运行")
            self._finished[identity] = True
            if len(self._finished) > 1024:
                self._finished.popitem(last=False)
            row.update(state="idle", outcome=outcome, updated=time.monotonic())
            message = f"{row['source']} · {row['name']}：{OUTCOMES[outcome]}"
            self._results.insert(0, {"text": message, "time": datetime.now().strftime("%H:%M"), "unread": True})
            del self._results[10:]
            self.changed.emit()
            title = " ".join(row["name"].split())
            if len(title) > 24:
                title = title[:24] + "…"
            self.completed.emit(f"「{title}」的会话结束了")
        else:
            raise ApiError("unknown_event", "未知会话事件")

    def prune(self):
        now = time.monotonic()
        expired = [key for key, row in self._sessions.items() if row["expires"] and row["expires"] < now]
        for key in expired:
            del self._sessions[key]
        if expired:
            self.changed.emit()

    @Slot()
    def markRead(self):
        if not any(row["unread"] for row in self._results):
            return
        for row in self._results:
            row["unread"] = False
        self.changed.emit()

    @Slot(str, str, str)
    def setPermission(self, instance, component, level):
        self.permissionRequested.emit(instance, component, level)

    def grant(self, instance, component, level):
        if instance in self._clients:
            self._clients[instance]["grants"][component] = level
            self.clientsChanged.emit()
            self.changed.emit()

    def grants(self, instance):
        return self._clients.get(instance, {}).get("grants", {})
