from .runtime import Runtime
from .authorization import Authorization
from .collaboration import Collaboration


def create_runtime():
    return Runtime()


def create_authorization():
    return Authorization()


def create_collaboration():
    return Collaboration()
