"""Provider-neutral, ephemeral sessions and connection permissions."""
from collections import OrderedDict
from datetime import datetime
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot
from .component_api import ApiError, arguments, text

OUTCOMES = {"ended": "本轮已结束", "failed": "本轮失败", "cancelled": "本轮已取消", "unknown": "本轮结束，结果未知"}


class AgentHub(QObject):
    name = "Agent"
    operations = [
        {"name": "session.status", "access": "read", "description": "即时统计全部已接入会话，返回执行中/空闲/断连数量及前20个执行中会话。以state为当前状态，outcome仅表示上一轮结果。",
         "parameters": {}, "returns": "{asOf,total,running,idle,disconnected,runningSessions,runningTruncated}", "example": {}},
        {"name": "session.list", "access": "read", "description": "查询已接入会话元数据，不含提示词或回复。",
         "parameters": {"offset?": "integer>=0", "limit?": "1..100，默认20"},
         "returns": "{total,sessions,nextOffset}", "example": {"limit": 20}},
        {"name": "result.list", "access": "read", "description": "最近十次结束结果，仅本次应用运行。",
         "parameters": {}, "returns": "{results,unreadCount}", "example": {}},
        {"name": "session.reply", "access": "read", "description": "读取指定会话最近一次结束时上报的助手回复，仅保留本次应用运行；available 表示有正文，truncated 表示正文被截断。执行新一轮时仍返回上一轮结束回复。",
         "parameters": {"instanceId": "string", "sessionId": "string"},
         "returns": "{instanceId,sessionId,available,runId?,outcome?,reply?,truncated?,endedAt?,reason?}",
         "example": {"instanceId": "连接ID", "sessionId": "会话ID"}},
        {"name": "session.send", "access": "write", "description": "向选定的已接入会话发送文字。start 开始新一轮，steer 追加指导。返回发送凭据，须查询 session.delivery 确认；超时不得自动重发。",
         "parameters": {"instanceId": "string", "sessionId": "string", "text": "1..8000字符", "mode": "start / steer"},
         "returns": "{deliveryId,status,applied}", "example": {"instanceId": "连接ID", "sessionId": "会话ID", "text": "继续检查", "mode": "start"}},
        {"name": "session.delivery", "access": "read", "description": "查询本次应用运行中的发送结果；accepted 仅表示目标接受消息。unknown 不得自动重发。",
         "parameters": {"deliveryId": "string"}, "returns": "{deliveryId,instanceId,sessionId,status,turnId,error}", "example": {"deliveryId": "发送凭据"}},
    ]
    commandRequested = Signal(str, dict)
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
        self._replies = OrderedDict()
        self._error = ""
        self._deliveries = OrderedDict()
        self._plugin_permissions = {}
        self._permissions_path = None

    sessions = Property("QVariantList", lambda self: [dict(row) for row in sorted(
        self._sessions.values(), key=lambda row: (row["state"] == "running", row["updated"]), reverse=True)], notify=changed)
    def _permission_clients(self):
        rows = []
        connected = set()
        for client in self._clients.values():
            identity = client.get("pluginId")
            if identity and identity in connected:
                continue
            row = dict(client)
            if identity:
                connected.add(identity)
                row["instanceId"] = "plugin:" + identity
            rows.append(row)
        for identity, saved in self._plugin_permissions.items():
            if identity not in connected:
                rows.append({"instanceId": "plugin:" + identity, "pluginId": identity,
                             "name": "Codex 插件" if identity == "polaris.codex" else saved["name"], "grants": dict(saved["grants"])})
        return rows

    clients = Property("QVariantList", _permission_clients, notify=clientsChanged)
    results = Property("QVariantList", lambda self: [dict(row) for row in self._results], notify=changed)
    unreadCount = Property(int, lambda self: sum(row["unread"] for row in self._results), notify=changed)
    connectionError = Property(str, lambda self: self._error, notify=changed)

    def call(self, operation, args):
        if operation == "session.reply":
            arguments(args, ("instanceId", "sessionId"), ("instanceId", "sessionId"))
            instance = text(args["instanceId"], "instanceId", 128)
            sid = text(args["sessionId"], "sessionId")
            result = self._replies.get((instance, sid))
            if result is not None:
                return dict(result)
            if (instance, sid) not in self._sessions:
                raise ApiError("unknown_session", "会话未接入或最近回复已过期")
            return {"instanceId": instance, "sessionId": sid, "available": False, "reason": "no_completed_run"}
        if operation == "session.send":
            return self.send_message(args)
        if operation == "session.delivery":
            arguments(args, ("deliveryId",), ("deliveryId",))
            identity = text(args["deliveryId"], "deliveryId", 128)
            self._expire_deliveries()
            row = self._deliveries.get(identity)
            if row is None:
                raise ApiError("unknown_delivery", "发送凭据不存在或已过期")
            return {key: value for key, value in row.items() if key != "deadline"}
        if operation == "session.status":
            arguments(args, ())
            rows = self.sessions
            running = [row for row in rows if row["state"] == "running"]
            fields = ("instanceId", "sessionId", "source", "name", "state")
            return {"asOf": datetime.now().astimezone().isoformat(), "total": len(rows),
                    "running": len(running), "idle": sum(row["state"] == "idle" for row in rows),
                    "disconnected": sum(row["state"] == "disconnected" for row in rows),
                    "runningSessions": [{key: row[key] for key in fields} for row in running[:20]],
                    "runningTruncated": len(running) > 20}
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
        fields = ("instanceId", "sessionId", "source", "name", "project", "state", "runId", "outcome", "sendModes")
        return {"total": len(rows), "sessions": [{key: row[key] for key in fields} for row in rows[offset:offset + limit]],
                "nextOffset": offset + limit if offset + limit < len(rows) else None}

    def set_error(self, message):
        self._error = message
        self.changed.emit()

    def load_permissions(self, directory):
        self._permissions_path = Path(directory) / "bridge" / "permissions.json"
        try:
            data = json.loads(self._permissions_path.read_text(encoding="utf8"))
            if not isinstance(data, dict):
                return
            self._plugin_permissions = {
                identity: {"name": row["name"], "grants": dict(row["grants"])}
                for identity, row in data.items()
                if isinstance(identity, str) and identity and len(identity) <= 128
                and isinstance(row, dict) and isinstance(row.get("name"), str)
                and isinstance(row.get("grants"), dict)
                and all(isinstance(key, str) and value in ("none", "read", "write")
                        for key, value in row["grants"].items())}
        except (OSError, ValueError):
            self._plugin_permissions = {}
        self.clientsChanged.emit()

    def _save_permissions(self):
        if self._permissions_path is None:
            return
        path = self._permissions_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("permissions-" + uuid4().hex + ".tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf8") as stream:
                json.dump(self._plugin_permissions, stream, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def connect_client(self, instance, name, plugin_id=None):
        # Older installed Codex helpers remain alive across a plugin file update.
        # Their two historical names belong to the same local plugin identity.
        if plugin_id is None and name in ("Codex hooks", "Codex tools"):
            plugin_id = "polaris.codex"
        if plugin_id == "polaris.codex":
            name = "Codex 插件"
        saved = self._plugin_permissions.get(plugin_id, {})
        self._clients[instance] = {"instanceId": instance, "name": name, "pluginId": plugin_id,
                                   "grants": dict(saved.get("grants", {}))}
        self.clientsChanged.emit()
        self.changed.emit()

    def disconnect_client(self, instance):
        self._clients.pop(instance, None)
        for row in self._deliveries.values():
            if row["instanceId"] == instance and row["status"] == "sending":
                row.update(status="unknown", error="disconnected")
        self.clientsChanged.emit()
        for (owner, _), row in self._sessions.items():
            if owner == instance:
                row.update(state="disconnected", expires=time.monotonic() + 30)
        self.changed.emit()

    def snapshot(self, instance, data):
        arguments(data, ("sessionId", "source", "name", "project", "state", "runId", "outcome", "sendModes"),
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
        modes = data.get("sendModes", [])
        if not isinstance(modes, list) or len(modes) > 2 or any(mode not in ("start", "steer") for mode in modes):
            raise ApiError("invalid_params", "sendModes 无效")
        key = instance, sid
        if state == "running" and (instance, sid, run) in self._finished:
            raise ApiError("invalid_state", "快照不得复用已经结束的 runId")
        if key not in self._sessions and len(self._sessions) >= 128:
            raise ApiError("limit_exceeded", "最多接入 128 个会话")
        self._sessions[key] = {"key": json.dumps(key), "instanceId": instance, "sessionId": sid,
                               "source": source, "name": name, "project": project, "state": state,
                               "runId": run, "outcome": outcome, "sendModes": list(dict.fromkeys(modes)), "updated": time.monotonic(), "expires": 0}
        self.changed.emit()  # Snapshots never produce completion notifications.

    def event(self, instance, event, data):
        if event == "session.snapshot":
            self.snapshot(instance, data)
            return
        allowed = ("sessionId",) if event == "session.removed" else (("sessionId", "runId", "outcome", "reply", "replyTruncated") if event == "run.ended" else ("sessionId", "runId", "outcome"))
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
            reply = data.get("reply")
            if reply is not None:
                reply = text(reply, "reply", 8000, empty=True)
            truncated = data.get("replyTruncated", False)
            if type(truncated) is not bool or (truncated and reply is None):
                raise ApiError("invalid_params", "replyTruncated 只能标记已上报的正文")
            identity = instance, sid, run
            if identity in self._finished:
                return
            if row["state"] != "running" or row["runId"] != run:
                raise ApiError("invalid_state", "结束事件不匹配当前运行")
            self._finished[identity] = True
            if len(self._finished) > 1024:
                self._finished.popitem(last=False)
            row.update(state="idle", outcome=outcome, updated=time.monotonic())
            result = {"instanceId": instance, "sessionId": sid, "runId": run,
                      "outcome": outcome, "available": reply is not None,
                      "endedAt": datetime.now().astimezone().isoformat()}
            if reply is not None:
                result.update(reply=reply, truncated=truncated)
            else:
                result["reason"] = "reply_not_reported"
            self._replies[key] = result
            self._replies.move_to_end(key)
            if len(self._replies) > 128:
                self._replies.popitem(last=False)
            message = f"{row['source']} · {row['name']}：{OUTCOMES[outcome]}"
            self._results.insert(0, {"text": message, "time": datetime.now().strftime("%H:%M"), "unread": True,
                                      "instanceId": instance, "sessionId": sid, "runId": run, "replyAvailable": reply is not None})
            del self._results[10:]
            self.changed.emit()
            title = " ".join(row["name"].split())
            if len(title) > 24:
                title = title[:24] + "…"
            self.completed.emit(f"「{title}」的会话结束了")
        else:
            raise ApiError("unknown_event", "未知会话事件")

    def _expire_deliveries(self):
        for row in self._deliveries.values():
            if row["status"] == "sending" and row["deadline"] <= time.monotonic():
                row.update(status="unknown", error="timeout")

    def send_message(self, args):
        arguments(args, ("instanceId", "sessionId", "text", "mode"), ("instanceId", "sessionId", "text", "mode"))
        instance = text(args["instanceId"], "instanceId", 128)
        sid = text(args["sessionId"], "sessionId")
        body = text(args["text"], "text", 8000)
        mode = args["mode"]
        if mode not in ("start", "steer"):
            raise ApiError("invalid_params", "mode 必须是 start 或 steer")
        row = self._sessions.get((instance, sid))
        if row is None or instance not in self._clients or row["state"] == "disconnected":
            raise ApiError("unavailable", "目标会话未连接")
        if mode not in row["sendModes"]:
            raise ApiError("unsupported", "目标未提供此发送能力")
        self._expire_deliveries()
        if any(item["instanceId"] == instance and item["sessionId"] == sid and item["status"] == "sending"
               for item in self._deliveries.values()):
            raise ApiError("send_pending", "目标已有消息发送中")
        if len(self._deliveries) >= 128:
            removable = next((key for key, item in self._deliveries.items() if item["status"] != "sending"), None)
            if removable is None:
                raise ApiError("limit_exceeded", "发送凭据已满")
            del self._deliveries[removable]
        identity = uuid4().hex
        self._deliveries[identity] = {"deliveryId": identity, "instanceId": instance, "sessionId": sid,
                                      "status": "sending", "turnId": "", "error": "", "deadline": time.monotonic() + 25}
        self.commandRequested.emit(instance, {"command": "session.send", "id": identity,
                                             "params": {"sessionId": sid, "text": body, "mode": mode}})
        return {"deliveryId": identity, "status": self._deliveries[identity]["status"], "applied": True}

    def command_result(self, instance, data):
        arguments(data, ("deliveryId", "sessionId", "status", "turnId", "error"), ("deliveryId", "sessionId", "status"))
        identity = text(data["deliveryId"], "deliveryId", 128)
        sid = text(data["sessionId"], "sessionId")
        status = data["status"]
        if status not in ("accepted", "failed", "unknown"):
            raise ApiError("invalid_params", "发送状态无效")
        turn = text(data.get("turnId", ""), "turnId", 128, empty=True)
        error = text(data.get("error", ""), "error", 64, empty=True)
        if status == "accepted" and not turn:
            raise ApiError("invalid_params", "accepted 必须包含目标运行 ID")
        row = self._deliveries.get(identity)
        if row is None or row["instanceId"] != instance or row["sessionId"] != sid:
            raise ApiError("unknown_delivery", "发送凭据与连接或会话不匹配")
        if row["status"] in ("sending", "unknown"):
            row.update(status=status, turnId=turn, error=error)

    def prune(self):
        self._expire_deliveries()
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
        client = self._clients.get(instance)
        plugin_id = client.get("pluginId") if client else None
        if client is None and instance.startswith("plugin:"):
            plugin_id = instance[len("plugin:"):]
            client = next((row for row in self._clients.values() if row.get("pluginId") == plugin_id), None)
            if client is None and plugin_id not in self._plugin_permissions:
                return
        if client is None and not plugin_id:
            return
        if plugin_id:
            previous = self._plugin_permissions.get(plugin_id)
            saved = {"name": client["name"] if client else previous["name"],
                     "grants": dict(previous["grants"]) if previous else {}}
            saved["grants"][component] = level
            self._plugin_permissions[plugin_id] = saved
            try:
                self._save_permissions()
            except OSError as error:
                if previous is None:
                    self._plugin_permissions.pop(plugin_id, None)
                else:
                    self._plugin_permissions[plugin_id] = previous
                self.set_error("授权保存失败：" + str(error))
                return
            for row in self._clients.values():
                if row.get("pluginId") == plugin_id:
                    row["grants"] = dict(saved["grants"])
        else:
            client["grants"][component] = level
        self.clientsChanged.emit()
        self.changed.emit()

    def grants(self, instance):
        return self._clients.get(instance, {}).get("grants", {})
