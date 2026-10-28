"""In-process Polaris tools. Independent read grants and one-shot desktop write approval."""
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from .component_api import ApiError, arguments, text


# The three hosts share one wire contract; each keeps its own permission policy.
_DEFINITIONS = json.loads((Path(__file__).resolve().parent.parent / "integrations" / "tools.json").read_text(encoding="utf8"))
TOOLS = [{"type": "function", "function": {
    "name": row["name"], "description": row["description"], "parameters": row["inputSchema"]}}
    for row in _DEFINITIONS]


class AgentTools(QObject):
    changed = Signal()

    def __init__(self, registry=None, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._reads = set()
        self._helped = set()
        self._pending = None
        self._callback = None
        self._denied = set()
        self._generation = 0
        self._tasks = {}
        self._expires_at = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.reject(self._pending["id"]) if self._pending else None)
        if registry is not None:
            registry.componentsChanged.connect(self.changed)

    components = Property("QVariantList", lambda self: [
        {**row, "readAllowed": row["id"] in self._reads}
        for row in (self._registry.components if self._registry is not None else [])], notify=changed)
    pending = Property("QVariantMap", lambda self: dict(self._pending) if self._pending else {}, notify=changed)

    @Slot(str, bool)
    def setReadAllowed(self, component, allowed):
        if self._registry is None:
            return
        try:
            self._registry.help(component)
        except ApiError:
            return
        if allowed:
            self._reads.add(component)
        else:
            self._reads.discard(component)
        self.changed.emit()

    def cancel(self, *, revoke=False):
        self._generation += 1
        self._timer.stop()
        self._pending = self._callback = None
        self._denied.clear()
        self._tasks.clear()
        if revoke:
            self._reads.clear()
            self._helped.clear()
        self.changed.emit()

    @staticmethod
    def _error(code, message):
        return {"ok": False, "error": {"code": code, "message": message}}

    def _execute(self, component, operation, params, *, write):
        try:
            result = self._registry.call(component, operation, params, {component: "write" if write else "read"})
            output = {"ok": True, "result": result}
            if len(json.dumps(output, ensure_ascii=False)) > 16000:
                output = {"ok": True, "resultOmitted": True,
                          "message": "结果过大，缩小读取范围；写操作已执行，不得重放"}
        except ApiError as error:
            output = self._error(error.code, str(error))
        except Exception as error:
            # Keep diagnostics free of component data and credentials.
            logging.getLogger(__name__).error("Component %s/%s raised %s", component, operation, type(error).__name__)
            output = self._error("outcome_unknown", "执行异常，写操作可能已应用；先查询实际状态，不得重放")
        return output

    def call(self, name, params, callback):
        try:
            if self._registry is None:
                raise ApiError("unavailable", "Polaris 组件接口未接入")
            if name == "polaris_components":
                arguments(params, ())
                callback({"ok": True, "components": self._registry.components})
                return
            if name == "polaris_help":
                arguments(params, ("component",), ("component",))
                component = text(params["component"], "component")
                result = self._registry.help(component)
                self._helped.add(component)
                callback({"ok": True, "result": result})
                return
            if name != "polaris_call":
                raise ApiError("unknown_tool", "工具未登记")
            arguments(params, ("component", "operation", "args"), ("component", "operation"))
            component, operation = text(params["component"], "component"), text(params["operation"], "operation")
            args = params.get("args", {})
            if component not in self._helped:
                raise ApiError("help_required", "本次连接须先读取该组件 help，再调用操作")
            if not isinstance(args, dict):
                raise ApiError("invalid_params", "args 必须是对象")
            definition = next((row for row in self._registry.help(component)["operations"]
                               if row["name"] == operation), None)
            if definition is None:
                raise ApiError("unknown_operation", "操作未登记，请先查询 help")
            if definition["access"] == "read":
                if component not in self._reads:
                    raise ApiError("permission_denied", "用户须在微信组件的工具权限中授权读取；不能借用其他 Agent 的权限")
                output = self._execute(component, operation, args, write=False)
                if component == "calendar" and operation == "task.list" and output.get("ok"):
                    for task in output.get("result", {}).get("tasks", []):
                        self._tasks[task["id"]] = dict(task)
                callback(output)
                return
            if self._pending is not None:
                raise ApiError("approval_pending", "已有写操作等待审批")
            encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if len(encoded) > 8000:
                raise ApiError("invalid_params", "写操作参数过大")
            if (component, operation, encoded) in self._denied:
                callback(self._error("approval_denied", "本轮已拒绝此请求，不重复申请"))
                return
            target = None
            if component == "calendar" and operation.startswith("task.") and operation not in (
                    "task.create", "task.restore", "task.move_overdue"):
                target = self._tasks.get(args.get("id"))
                if target is None or (operation == "task.reorder" and args.get("beforeId") not in self._tasks):
                    raise ApiError("target_lookup_required", "先用 task.list 按用户给出的标题查询，使用返回的真实 id；数字标题不是ID。重名须让用户确认日期。")
            description = definition["description"]
            if target is not None:
                description += "\n目标标题：" + target["title"] + "；日期：" + str(target.get("date") or "收集箱")
            self._pending = {"id": uuid4().hex, "component": component, "operation": operation,
                             "description": description, "arguments": encoded}
            self._callback = callback
            self._expires_at = time.monotonic() + 120
            self._timer.start(120000)
            self.changed.emit()
        except (ApiError, ValueError, TypeError) as error:
            callback(self._error(getattr(error, "code", "invalid_params"), str(error)))

    @Slot(str)
    def approve(self, identity):
        if not self._pending or identity != self._pending["id"]:
            return
        if time.monotonic() >= self._expires_at:
            self.reject(identity)
            return
        pending, callback = self._pending, self._callback
        generation = self._generation
        self._pending = self._callback = None
        self._timer.stop()
        self.changed.emit()
        # Exact immutable parameters displayed locally; approval is consumed before execution.
        if generation != self._generation:
            return
        callback(self._execute(pending["component"], pending["operation"],
                               json.loads(pending["arguments"]), write=True))

    @Slot(str)
    def reject(self, identity):
        if not self._pending or identity != self._pending["id"]:
            return
        pending, callback = self._pending, self._callback
        self._pending = self._callback = None
        self._timer.stop()
        self.changed.emit()
        output = self._error("approval_denied", "用户拒绝或审批超时，未执行此写操作；本轮不要再次申请")
        self._denied.add((pending["component"], pending["operation"], pending["arguments"]))
        callback(output)
