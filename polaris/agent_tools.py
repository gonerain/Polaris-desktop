"""In-process tools with independent reads and request-scoped write-plan approval."""
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from .component_api import ApiError, arguments, text
from .write_plan import WritePlan, PLAN_TOOL


# The three hosts share one wire contract; each keeps its own permission policy.
_DEFINITIONS = json.loads((Path(__file__).resolve().parent.parent / "integrations" / "tools.json").read_text(encoding="utf8"))
TOOLS = [{"type": "function", "function": {
    "name": row["name"], "description": ("微信 Agent 用此工具读取业务数据；写入须用 polaris_plan 提交完整计划。"
                                          if row["name"] == "polaris_call" else "") + row["description"],
    "parameters": row["inputSchema"]}}
    for row in _DEFINITIONS]
TOOLS.append(PLAN_TOOL)


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
        self._request = ""
        self._auto_low_risk = True
        self._pending_plan = None
        self._spent = 0
        self._submitted = set()
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
    autoLowRisk = Property(bool, lambda self: self._auto_low_risk, notify=changed)

    @Slot(bool)
    def setAutoLowRisk(self, enabled):
        # Changing policy never approves an already-pending plan.
        self._auto_low_risk = bool(enabled)
        self.changed.emit()

    def begin_request(self, body):
        self.cancel()
        self._request = body

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
        self._pending_plan = None
        self._request = ""
        self._spent = 0
        self._submitted.clear()
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
            if component == "calendar" and operation == "task.create" and isinstance(result.get("task"), dict):
                self._tasks[result["task"]["id"]] = dict(result["task"])
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
            if name == "polaris_plan":
                if not self._request:
                    raise ApiError("request_required", "操作计划须属于当前用户请求")
                self._submit_plan(params, callback)
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
            raise ApiError("plan_required", "写操作须用 polaris_plan 一次提交当前请求的完整计划；不能按工具逐项申请审批。")
        except (ApiError, ValueError, TypeError) as error:
            callback(self._error(getattr(error, "code", "invalid_params"), str(error)))

    def _check_target(self, step, args):
        if step["component"] != "calendar":
            return None
        operation = step["operation"]
        identity = args.get("taskId") if operation.startswith(("subtask.", "notes.")) else args.get("id")
        needs_target = (operation.startswith(("subtask.", "notes.")) or
                        (operation.startswith("task.") and operation not in ("task.create", "task.restore", "task.move_overdue")))
        if not needs_target:
            return None
        target = self._tasks.get(identity)
        if target is None or (operation == "task.reorder" and args.get("beforeId") not in self._tasks):
            raise ApiError("target_lookup_required", "先用 task.list 查询真实ID；新建父任务可引用该计划前面步骤的 task.id。数字标题不是ID。")
        return target

    def _submit_plan(self, params, callback):
        if self._pending is not None:
            raise ApiError("approval_pending", "已有计划等待审批；不能扩大或替换其范围")
        plan = WritePlan(params, self._registry, self._helped)
        signature = plan.key
        if signature in self._denied:
            raise ApiError("approval_denied", "本轮已拒绝该计划，不重复申请")
        if plan.key in self._submitted:
            raise ApiError("plan_already_submitted", "本轮已执行或尝试过此计划；先查询实际状态，不得重放")
        if self._spent + len(plan.steps) > 8:
            raise ApiError("plan_limit", "当前请求的写步骤总数不能超过8步")
        expanded = self._spent > 0
        preview = ["用户请求：" + self._request[:500], "风险：" + ("低（仅新增）" if plan.risk == "low" else "需确认"),
                   "一次批准仅覆盖下列固定步骤；失败停止，已执行部分不回滚。"]
        for step, description in zip(plan.steps, plan.descriptions):
            preview.append(step["id"] + ": " + step["component"] + " / " + step["operation"] + " · " + description)
            # References are validated by WritePlan and resolved to earlier results only.
            if not any(isinstance(value, dict) and "$ref" in value for value in step["args"].values()):
                target = self._check_target(step, step["args"])
                if target is not None:
                    preview.append("目标标题：" + target["title"] + "；日期：" + str(target.get("date") or "收集箱"))
        self._spent += len(plan.steps)
        if plan.risk == "low" and self._auto_low_risk and not expanded:
            self._submitted.add(plan.key)
            callback(self._execute_plan(plan))
            return
        self._pending_plan = plan
        if expanded:
            preview.append("这是当前请求的追加计划，需要重新批准；之前的授权不覆盖新增动作。")
        self._pending = {"id": uuid4().hex, "component": "操作计划", "operation": f"执行 {len(plan.steps)} 步",
                         "description": "\n".join(preview), "arguments": plan.encoded}
        self._callback = callback
        self._expires_at = time.monotonic() + 120
        self._timer.start(120000)
        self.changed.emit()

    def _execute_plan(self, plan):
        results, completed = {}, []
        generation = self._generation
        for index, step in enumerate(plan.steps):
            if generation != self._generation:
                return self._error("request_cancelled", "请求已取消，停止剩余计划")
            try:
                args = plan.resolve(step["args"], results)
                self._check_target(step, args)
                output = self._execute(step["component"], step["operation"], args, write=True)
            except ApiError as error:
                output = self._error(error.code, str(error))
            completed.append({"id": step["id"], **output})
            result = output.get("result", {})
            if not output.get("ok") or output.get("resultOmitted") or result.get("storageError"):
                return {"ok": False, "error": {"code": "plan_stopped", "message": "计划中断；核对已执行部分，不得重放整个计划"},
                        "steps": completed, "unexecuted": [row["id"] for row in plan.steps[index + 1:]],
                        "applied": any(row.get("ok") for row in completed) or output.get("error", {}).get("code") == "outcome_unknown"}
            results[step["id"]] = result
        return {"ok": True, "result": {"steps": completed, "risk": plan.risk, "applied": True}}

    @Slot(str)
    def approve(self, identity):
        if not self._pending or identity != self._pending["id"]:
            return
        if time.monotonic() >= self._expires_at:
            self.reject(identity)
            return
        pending, callback, plan = self._pending, self._callback, self._pending_plan
        generation = self._generation
        self._pending = self._callback = None
        self._pending_plan = None
        self._timer.stop()
        self.changed.emit()
        # Exact immutable parameters displayed locally; approval is consumed before execution.
        if generation != self._generation:
            return
        self._submitted.add(plan.key)
        callback(self._execute_plan(plan))

    @Slot(str)
    def reject(self, identity):
        if not self._pending or identity != self._pending["id"]:
            return
        pending, callback, plan = self._pending, self._callback, self._pending_plan
        self._pending = self._callback = None
        self._pending_plan = None
        self._timer.stop()
        self.changed.emit()
        output = self._error("approval_denied", "用户拒绝或审批超时，未执行此写操作；本轮不要再次申请")
        self._denied.add(plan.key)
        callback(output)
