"""Compatibility imports for the bundled window component."""
from components.window import WindowHost, QGuiApplication, create_window
from .qt_ports import GuiDispatcher, NativeQtProfilePort, ResourceCleanupPort
