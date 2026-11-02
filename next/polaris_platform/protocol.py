"""Portable protocol values; no business types."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


class PlatformError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class Context:
    origin: str
    caller: str
    source: str
    scope: frozenset = field(default_factory=frozenset)
    origin_installation: str = ""
    request_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)
    _seal: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Handle:
    target: str
    instance: str
    operation: str
    semantic: tuple
    contract: str | None = None
    generation: int = 0


def capability(installation, kind, name, metadata):
    return (installation, kind, name, int(metadata.get("major", 1)),
            metadata.get("access", "read"), int(metadata.get("revision", 1)))


# Checked by the SDK at handler lookup, including across stdio. A concurrent
# registration cannot replace an already-authorized read with a write.
_dispatched = ContextVar('polaris_dispatched_capability', default=None)


def handler_signature(metadata):
    return (metadata.get('major', 1), metadata.get('access', 'read'), metadata.get('revision', 1),
            metadata.get('provides'))


def validate_description(description):
    """Validate protocol metadata only; payload semantics belong to providers."""
    if not isinstance(description, dict):
        raise PlatformError("invalid_description", "Description must be an object")
    for group in ("operations", "events"):
        entries = description.get(group, {})
        if not isinstance(entries, dict):
            raise PlatformError("invalid_description", f"{group} must be a map")
        for name, metadata in entries.items():
            if not isinstance(name, str) or not name or not isinstance(metadata, dict):
                raise PlatformError("invalid_description", "Capabilities require names and metadata")
            if metadata.get("access", "read") not in ("read", "write"):
                raise PlatformError("invalid_description", "Access must be read or write")
            for version in ("major", "revision"):
                value = metadata.get(version, 1)
                if type(value) is not int or value < 1:
                    raise PlatformError("invalid_description", f"{version} must be a positive integer")
    for group in ("views", "dependencies"):
        if not isinstance(description.get(group, []), list):
            raise PlatformError("invalid_description", f"{group} must be a list")
    from .contracts import validate_contracts
    validate_contracts(description)
    return description
