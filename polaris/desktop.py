"""Optional system tray: a persistent escape hatch and native reminder channel."""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def create_tray(app, window, coordinator, data_directory):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    icon = QIcon(str(Path(__file__).resolve().parent.parent / "assets/dsh-pet/poster.webp"))
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Polaris · 日程 / Agent")
    menu = QMenu()
    menu.addAction("打开日程", lambda: window.showPage("calendar"))
    menu.addAction("Agent 会话", lambda: window.showPage("agents"))
    menu.addAction("打开数据文件夹", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_directory))))
    menu.addSeparator()
    menu.addAction("退出", window.requestQuit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: window.expand() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    coordinator.notification.connect(lambda kind, identity, text: tray.showMessage(
        "Polaris · 日程提醒", text, QSystemTrayIcon.MessageIcon.Information, 10_000)
        if kind == "task.upcoming" else None)
    # Keep the Python-owned menu alive for the tray's entire lifetime.
    tray._menu = menu
    tray.show()
    return tray
