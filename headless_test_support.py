"""GUI 测试只能使用离屏、软件后端；不得连接真实显示服务。"""

import os
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ.pop("DISPLAY", None)
os.environ.pop("WAYLAND_DISPLAY", None)

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from polaris.qml import register_types

QML_DIRECTORY = Path(__file__).resolve().parent / "qml"


def find_visual_item(parent, name):
    if parent.objectName() == name:
        return parent
    for child in parent.childItems():
        found = find_visual_item(child, name)
        if found is not None:
            return found
    return None


class HeadlessQtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = QGuiApplication.instance()
        if app is not None and app.platformName() != "offscreen":
            raise RuntimeError("测试禁止连接真实桌面")
        if app is None:
            QQuickWindow.setSceneGraphBackend("software")
            app = QGuiApplication([])
        elif QQuickWindow.sceneGraphBackend() != "software":
            raise RuntimeError("测试只能使用软件渲染")
        cls.app = app
        cls.app.setQuitOnLastWindowClosed(False)
        register_types()

    def load_window(self, source):
        engine = QQmlApplicationEngine()
        engine.addImportPath(str(QML_DIRECTORY))
        engine.loadData(source.encode(), QUrl.fromLocalFile(str(QML_DIRECTORY / "Test.qml")))
        self.assertTrue(engine.rootObjects(), "QML 界面加载失败")
        window = engine.rootObjects()[0]
        self.addCleanup(self.close_engine, engine, window)
        self.assertTrue(QTest.qWaitForWindowExposed(window, 3000))
        QTest.qWait(30)
        return window

    def close_engine(self, engine, window):
        window.close()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def item(self, window, name):
        result = find_visual_item(window.contentItem(), name)
        self.assertIsNotNone(result, name)
        return result
