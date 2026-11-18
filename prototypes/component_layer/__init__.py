"""Prototype of component-owned capabilities and caller-owned collaboration."""
from .core import (
    CallContext,
    Component,
    ComponentError,
    ComponentSpec,
    Grant,
    OperationSpec,
    Permission,
    Registry,
)

__all__ = [
    "CallContext", "Component", "ComponentError", "ComponentSpec", "Grant",
    "OperationSpec", "Permission", "Registry",
]
