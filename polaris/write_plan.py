"""Bounded write plans: immutable scope, host-owned risk and backward ID references."""
import json
import re

from .component_api import ApiError, arguments, text


PLAN_TOOL = {"type": "function", "function": {
    "name": "polaris_plan",
    "description": "提交当前用户请求的完整写操作计划。先发现/help/查询真实ID，再一次提交全部写步骤。风险由程序判断：纯新增任务/子任务自动执行，其余计划整体批准一次；不允许扩大已批准计划。新建父任务和子任务放在同一计划，taskId可用{\"$ref\":\"parent.task.id\"}引用前面parent步骤的结果。失败即停止，不回滚、不重放。",
    "parameters": {"type": "object", "properties": {
        "steps": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
            "type": "object", "properties": {
                "id": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9_]{0,31}$"},
                "component": {"type": "string"}, "operation": {"type": "string"},
                "args": {"type": "object", "additionalProperties": True}},
            "required": ["id", "component", "operation", "args"], "additionalProperties": False}}},
        "required": ["steps"], "additionalProperties": False}}}

# Unknown operations always require confirmation. The model cannot label its own risk.
ADDITIONS = frozenset({("calendar", "task.create"), ("calendar", "subtask.create")})


class WritePlan:
    def __init__(self, params, registry, helped):
        arguments(params, ("steps",), ("steps",))
        self.encoded = json.dumps(params, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(self.encoded) > 8000:
            raise ApiError("invalid_params", "操作计划过大，最多8000字符")
        self.steps = json.loads(self.encoded)["steps"]
        if not isinstance(self.steps, list) or not 1 <= len(self.steps) <= 8:
            raise ApiError("invalid_params", "计划须包含1至8个步骤")
        previous = {}
        self.descriptions = []
        for step in self.steps:
            arguments(step, ("id", "component", "operation", "args"), ("id", "component", "operation", "args"))
            identity = text(step["id"], "step.id", 32)
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,31}", identity) or identity in previous:
                raise ApiError("invalid_params", "计划步骤ID须唯一且为英文字母、数字、下划线")
            component, operation = text(step["component"], "component"), text(step["operation"], "operation")
            if component not in helped:
                raise ApiError("help_required", "计划中的组件须先读取 help")
            definition = next((row for row in registry.help(component)["operations"] if row["name"] == operation), None)
            if definition is None or definition["access"] != "write":
                raise ApiError("invalid_params", "计划只接受已登记写操作，业务读取须先单独授权查询")
            if not isinstance(step["args"], dict):
                raise ApiError("invalid_params", "计划参数须为对象")
            for key, value in step["args"].items():
                if isinstance(value, dict) and "$ref" in value:
                    arguments(value, ("$ref",), ("$ref",))
                    match = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9_]{0,31})\.(task|subtask)\.id", text(value["$ref"], "$ref"))
                    source = previous.get(match[1]) if match else None
                    if (source is None or source["component"] != "calendar"
                            or source["operation"] != match[2] + ".create"
                            or key not in ("id", "taskId", "subtaskId", "beforeId")):
                        raise ApiError("invalid_reference", "只能在ID参数引用前面新建任务/子任务步骤返回的ID")
                    if (key == "taskId" and match[2] != "task") or (key == "subtaskId" and match[2] != "subtask"):
                        raise ApiError("invalid_reference", "父任务ID和子任务ID不能混用")
            references = {key: value for key, value in step["args"].items()
                          if isinstance(value, dict) and "$ref" in value}
            # IDs do not exist yet: validate their parameter shape with a positive ID,
            # then retain the validated symbolic bindings in the immutable plan.
            prepared = registry.prepare_write(component, operation,
                                              {key: 1 if key in references else value for key, value in step["args"].items()})
            prepared.update(references)
            step["args"] = prepared
            previous[identity] = step
            self.descriptions.append(definition["description"])
        self.risk = "low" if all((step["component"], step["operation"]) in ADDITIONS for step in self.steps) else "confirm"
        self.encoded = json.dumps({"steps": self.steps}, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(self.encoded) > 8000:
            raise ApiError("invalid_params", "规范化后的操作计划超过8000字符")
        normalized = json.loads(self.encoded)
        aliases = {step["id"]: "s" + str(index) for index, step in enumerate(self.steps)}
        for step in normalized["steps"]:
            step["id"] = aliases[step["id"]]
            for value in step["args"].values():
                if isinstance(value, dict) and "$ref" in value:
                    name, rest = value["$ref"].split(".", 1)
                    value["$ref"] = aliases[name] + "." + rest
        self.key = json.dumps(normalized, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def resolve(args, results):
        resolved = dict(args)
        for key, value in args.items():
            if isinstance(value, dict) and "$ref" in value:
                step, kind, _ = value["$ref"].split(".")
                try:
                    resolved[key] = results[step][kind]["id"]
                except (KeyError, TypeError):
                    raise ApiError("invalid_reference", "前置步骤没有返回预期ID，已停止后续步骤") from None
        return resolved
