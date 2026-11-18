"""Component discovery, explicit authority and calls, without business workflows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol
from uuid import uuid4


class ComponentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OperationSpec:
    name: str
    access: str
    description: str
    parameters: str = ""
    returns: str = ""
    version: int = 1


@dataclass(frozen=True)
class ComponentSpec:
    id: str
    name: str
    operations: tuple[OperationSpec, ...]

    def __post_init__(self):
        object.__setattr__(self, "operations", tuple(self.operations))


class Component(Protocol):
    spec: ComponentSpec

    def call(self, operation: str, args: Any, context: CallContext) -> Any:
        """Validate and implement this component's operation."""
        ...


@dataclass(frozen=True)
class Permission:
    component: str
    operation: str
    version: int
    generation: int


@dataclass(frozen=True)
class Grant:
    id: str
    principal: str
    source: str
    scope: frozenset[Permission]


@dataclass(frozen=True)
class _Registration:
    component: Component
    spec: ComponentSpec
    generation: int


@dataclass(frozen=True)
class CallContext:
    """A request's authority; nested calls preserve it and may only narrow it.

    Components receive this interface, not the host's grant-issuing interface.
    This is a cooperation boundary for trusted Python code, not a sandbox.
    """

    _registry: Registry
    _grant: Grant
    _scope: frozenset[Permission]
    request_id: str
    call_chain: tuple[tuple[str, str], ...] = ()

    @property
    def principal(self) -> str:
        return self._grant.principal

    @property
    def source(self) -> str:
        return self._grant.source

    @property
    def scope(self) -> frozenset[Permission]:
        return self._scope

    def discover(self) -> tuple[ComponentSpec, ...]:
        return self._registry.discover()

    def help(self, component: str) -> ComponentSpec:
        return self._registry.help(component)

    def call(self, component: str, operation: str, args: Any) -> Any:
        return self._registry._call(self, component, operation, args)

    def narrow(self, operations: Iterable[tuple[str, str]]) -> CallContext:
        requested = _operation_keys(operations)
        available = {(item.component, item.operation): item for item in self._scope}
        if not requested <= available.keys():
            raise ComponentError("permission_denied", "不能扩大当前调用的授权范围")
        return CallContext(self._registry, self._grant,
                           frozenset(available[key] for key in requested),
                           self.request_id, self.call_chain)


class Registry:
    """Host-owned capability registry. It neither creates nor stops components."""

    def __init__(self):
        self._components: dict[str, _Registration] = {}
        self._grants: dict[str, Grant] = {}
        self._generation = 0

    def register(self, component: Component) -> None:
        spec = _snapshot(component.spec)
        if spec.id in self._components:
            raise ComponentError("duplicate_component", "组件已登记")
        self._install(component, spec)

    def update(self, component: Component) -> None:
        spec = _snapshot(component.spec)
        self._get(spec.id)
        self._install(component, spec)

    def _install(self, component: Component, spec: ComponentSpec) -> None:
        if not callable(getattr(component, "call", None)):
            raise ComponentError("invalid_contract", "组件必须提供 call 接口")
        self._generation += 1
        self._components[spec.id] = _Registration(component, spec, self._generation)

    def unregister(self, identity: str) -> None:
        self._get(identity)
        del self._components[identity]

    def discover(self) -> tuple[ComponentSpec, ...]:
        return tuple(row.spec for row in self._components.values())

    def help(self, identity: str) -> ComponentSpec:
        return self._get(identity).spec

    def issue_grant(self, *, principal: str, source: str,
                    operations: Iterable[tuple[str, str]]) -> Grant:
        """Trusted host action, after its own authorization policy has allowed it."""
        _nonempty(principal, "principal", "invalid_grant")
        _nonempty(source, "source", "invalid_grant")
        scope = []
        for identity, operation in sorted(_operation_keys(operations)):
            registration, definition = self._operation(identity, operation)
            scope.append(Permission(identity, operation, definition.version,
                                    registration.generation))
        grant = Grant(uuid4().hex, principal, source, frozenset(scope))
        self._grants[grant.id] = grant
        return grant

    def revoke(self, grant: Grant) -> None:
        if self._grants.get(grant.id) is grant:
            del self._grants[grant.id]

    def context(self, grant: Grant, request_id: str) -> CallContext:
        self._check_grant(grant)
        _nonempty(request_id, "request_id", "invalid_request")
        return CallContext(self, grant, grant.scope, request_id)

    def _check_grant(self, grant: Grant) -> None:
        if not isinstance(grant, Grant) or self._grants.get(grant.id) is not grant:
            raise ComponentError("permission_denied", "授权不存在或已撤销")

    def _get(self, identity: str) -> _Registration:
        if not isinstance(identity, str) or identity not in self._components:
            raise ComponentError("unknown_component", "组件未登记")
        return self._components[identity]

    def _operation(self, identity: str, operation: str):
        registration = self._get(identity)
        for definition in registration.spec.operations:
            if definition.name == operation:
                return registration, definition
        raise ComponentError("unknown_operation", "组件未声明此操作")

    def _call(self, context: CallContext, identity: str, operation: str, args: Any) -> Any:
        self._check_grant(context._grant)
        registration, definition = self._operation(identity, operation)
        permission = Permission(identity, operation, definition.version,
                                registration.generation)
        if (context._registry is not self or not context._scope <= context._grant.scope
                or permission not in context._scope):
            raise ComponentError("permission_denied", "当前调用未获此操作授权，或组件登记已变化")
        nested = CallContext(self, context._grant, context._scope, context.request_id,
                             context.call_chain + ((identity, operation),))
        # Each operation owns its data contract and validation. The caller owns
        # collaboration and failure handling; this layer only routes the call.
        return registration.component.call(operation, args, nested)


def _nonempty(value: Any, name: str, code: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ComponentError(code, f"{name} 必须是非空字符串")


def _snapshot(spec: ComponentSpec) -> ComponentSpec:
    if not isinstance(spec, ComponentSpec):
        raise ComponentError("invalid_contract", "组件必须声明 ComponentSpec")
    _nonempty(spec.id, "component.id", "invalid_contract")
    _nonempty(spec.name, "component.name", "invalid_contract")
    names = set()
    operations = []
    for operation in spec.operations:
        if not isinstance(operation, OperationSpec):
            raise ComponentError("invalid_contract", "操作必须声明 OperationSpec")
        _nonempty(operation.name, "operation.name", "invalid_contract")
        _nonempty(operation.description, "operation.description", "invalid_contract")
        if (operation.name in names or operation.access not in ("read", "write")
                or type(operation.version) is not int or operation.version < 1
                or not isinstance(operation.parameters, str)
                or not isinstance(operation.returns, str)):
            raise ComponentError("invalid_contract", "操作声明重复或格式无效")
        names.add(operation.name)
        operations.append(OperationSpec(operation.name, operation.access, operation.description,
                                        operation.parameters, operation.returns, operation.version))
    return ComponentSpec(spec.id, spec.name, tuple(operations))


def _operation_keys(operations: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    try:
        entries = list(operations)
    except TypeError:
        raise ComponentError("invalid_grant", "授权范围须为组件与操作的列表") from None
    keys = set()
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ComponentError("invalid_grant", "授权项须包含组件和操作")
        identity, operation = entry
        _nonempty(identity, "component", "invalid_grant")
        _nonempty(operation, "operation", "invalid_grant")
        keys.add((identity, operation))
    return keys
