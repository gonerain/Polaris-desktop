"""Polaris independent component platform."""
from .metadata import VERSION as __version__
from .component import Component
from .protocol import Context, Handle, PlatformError


def __getattr__(name):
    if name in ('Runtime', 'Client'):
        from . import runtime
        return getattr(runtime, name)
    raise AttributeError(name)

__all__ = ["Component", "Context", "Handle", "PlatformError", "Runtime", "Client"]
