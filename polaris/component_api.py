"""Small, explicit business interfaces. No QObject reflection or plugin loading."""
from PySide6.QtCore import QObject, Property, Signal


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def text(value, name, maximum=256, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum:
        raise ApiError("invalid_params", f"{name} 必须是有效字符串，最长 {maximum} 字符")
    try:
        value.encode("utf8")
    except UnicodeError:
        raise ApiError("invalid_params", f"{name} 含无效 Unicode") from None
    return value


def arguments(value, allowed, required=()):
    if not isinstance(value, dict) or value.keys() - set(allowed) or set(required) - value.keys():
        raise ApiError("invalid_params", "参数缺失或含未知字段；请先查询组件 help")
    return value


class ComponentRegistry(QObject):
    componentsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._components = {}

    components = Property("QVariantList", lambda self: [
        {"id": key, "name": api.name, "writable": any(op["access"] == "write" for op in api.operations)}
        for key, api in self._components.items()
    ], notify=componentsChanged)

    def register(self, identity, api):
        if identity in self._components:
            raise ValueError(f"Duplicate component: {identity}")
        names = [entry["name"] for entry in api.operations]
        if len(names) != len(set(names)) or any(entry["access"] not in ("read", "write") for entry in api.operations):
            raise ValueError("Component operation names must be unique, with explicit read/write access")
        self._components[identity] = api
        self.componentsChanged.emit()

    def help(self, identity):
        api = self._get(identity)
        return {"component": identity, "name": api.name, "version": 1,
                "operations": api.operations}

    def _get(self, identity):
        if not isinstance(identity, str) or identity not in self._components:
            raise ApiError("unknown_component", "组件未登记")
        return self._components[identity]

    def call(self, identity, operation, args, grants):
        api = self._get(identity)
        definition = next((entry for entry in api.operations if entry["name"] == operation), None)
        if definition is None:
            raise ApiError("unknown_operation", "操作未登记；请查询 help")
        level = grants.get(identity, "none")
        if level not in ("read", "write") or (definition["access"] == "write" and level != "write"):
            raise ApiError("permission_denied", "请用户在 Polaris 的 Agent 面板点击 ↗，授权此连接访问该组件")
        if not isinstance(args, dict):
            raise ApiError("invalid_params", "args 必须是对象")
        return api.call(operation, args)
