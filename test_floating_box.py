"""悬浮框的离屏测试：点击展开、鼠标离开缩回、尺寸记忆。"""

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ.pop("DISPLAY", None)
os.environ.pop("WAYLAND_DISPLAY", None)

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

from main import create_engine


def find_visual_item(parent, name):
    if parent.objectName() == name:
        return parent
    for child in parent.childItems():
        found = find_visual_item(child, name)
        if found is not None:
            return found
    return None


class FloatingBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = QGuiApplication.instance()
        if app is not None and app.platformName() != "offscreen":
            raise RuntimeError("测试禁止使用连接真实桌面的 Qt 应用实例")
        if app is None:
            QQuickWindow.setSceneGraphBackend("software")
            app = QGuiApplication([])
        elif QQuickWindow.sceneGraphBackend() != "software":
            raise RuntimeError("测试只能使用软件渲染")
        cls.app = app
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self) -> None:
        self.engine = create_engine()
        self.window = self.engine.rootObjects()[0]
        self.addCleanup(self.close_window)
        self.assertIsInstance(self.window, QQuickWindow)
        self.assertTrue(QTest.qWaitForWindowExposed(self.window, 3000))
        QTest.qWait(50)

    def close_window(self) -> None:
        self.window.close()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def find(self, name: str):
        result = find_visual_item(self.window.contentItem(), name)
        self.assertIsNotNone(result, name)
        return result

    def click(self, name: str) -> None:
        item = self.find(name)
        position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, pos=position)
        self.app.processEvents()
        QTest.qWait(100)

    def expand(self) -> None:
        self.click("compactBox")
        QTest.qWait(220)
        self.assertFalse(self.window.property("compact"))

    def hover_inside(self) -> None:
        QTest.mouseMove(self.window, QPoint(300, 150))
        QTest.qWait(30)

    def hover_outside(self) -> None:
        QTest.mouseMove(self.window, QPoint(max(self.window.width() + 20, 50),
                                            max(self.window.height() + 20, 50)))
        QTest.qWait(30)

    def test_starts_as_compact_floating_box(self) -> None:
        self.assertTrue(self.window.property("compact"))
        self.assertEqual((self.window.width(), self.window.height()), (180, 180))
        self.assertEqual((self.window.minimumWidth(), self.window.minimumHeight()), (180, 180))
        self.assertTrue(self.find("compactBox").isVisible())
        self.assertEqual(self.window.color().alpha(), 0)
        pet = self.find("petMascot")
        self.assertTrue(pet.isVisible())
        self.assertEqual((pet.width(), pet.height()), (180, 180))
        self.assertIn(pet.property("frameName"), ["idle_pillow_awake", "idle_pillow_blink"])
        self.assertIn(".webp", str(self.find("petFrameImage").property("source")))
        self.assertFalse(self.find("expandedContent").isVisible())
        board = self.find("componentBoard")
        self.assertEqual((board.width(), board.height()), (528, 256))
        calendar = self.find("calendarTasks")
        self.assertFalse(calendar.isVisible())
        self.assertFalse(calendar.property("calendarVisible"))
        self.assertFalse(self.find("calendarMonthView").isVisible())
        self.assertFalse(self.find("newTaskInput").isVisible())

    def test_right_click_on_pet_opens_quit_menu(self) -> None:
        menu = self.window.findChild(QObject, "quitMenu")
        self.assertIsNotNone(menu)
        self.assertFalse(menu.property("visible"))

        QTest.mouseClick(self.window, Qt.MouseButton.RightButton, pos=QPoint(90, 90))
        QTest.qWait(120)
        self.assertTrue(menu.property("visible"))

        menu.setProperty("visible", False)

    def test_click_compact_box_expands(self) -> None:
        self.expand()
        self.assertEqual((self.window.width(), self.window.height()), (528, 300))
        self.assertEqual((self.window.minimumWidth(), self.window.minimumHeight()), (528, 300))
        self.assertFalse(self.find("compactBox").isVisible())
        self.assertTrue(self.find("expandedContent").isVisible())
        self.assertTrue(self.find("calendarTasks").isVisible())
        self.assertFalse(self.find("calendarTasks").property("calendarVisible"))
        self.assertTrue(self.find("openComposerButton").isVisible())
        self.assertFalse(self.find("newTaskInput").isVisible())
        self.assertEqual(self.find("componentBoard").property("freePanelCount"), 0)

    def test_mouse_leave_collapses_and_reenter_cancels(self) -> None:
        self.expand()
        self.hover_inside()
        self.assertTrue(self.window.findChild(QObject, "windowHover").property("hovered"))

        self.hover_outside()
        QTest.qWait(150)
        self.assertFalse(self.window.property("compact"))
        self.hover_inside()
        QTest.qWait(500)
        self.assertFalse(self.window.property("compact"))

        self.hover_outside()
        QTest.qWait(700)
        self.assertTrue(self.window.property("compact"))
        self.assertEqual((self.window.width(), self.window.height()), (180, 180))

    def test_pet_waves_when_the_pointer_enters(self) -> None:
        QTest.mouseMove(self.window, QPoint(320, 320))
        QTest.qWait(800)
        pet = self.find("petMascot")
        self.assertFalse(pet.property("waving"))

        QTest.mouseMove(self.window, QPoint(90, 90))
        QTest.qWait(80)
        self.assertTrue(pet.property("waving"))
        self.assertTrue(str(pet.property("frameName")).startswith("idle_pillow_"))

    def test_collapse_can_be_cancelled_during_fade(self) -> None:
        self.expand()
        self.hover_inside()
        self.hover_outside()
        QTest.qWait(450)
        self.assertTrue(self.window.property("collapsing"))
        self.assertFalse(self.window.property("compact"))

        self.hover_inside()
        QTest.qWait(300)
        self.assertFalse(self.window.property("collapsing"))
        self.assertFalse(self.window.property("compact"))

    def test_expanded_size_is_remembered(self) -> None:
        self.expand()
        self.window.resize(800, 500)
        self.app.processEvents()
        QTest.qWait(100)
        self.hover_outside()
        QTest.qWait(700)
        self.assertTrue(self.window.property("compact"))

        self.expand()
        self.assertEqual((self.window.width(), self.window.height()), (800, 500))
        self.assertEqual((self.find("calendarTasks").width(),
                          self.find("calendarTasks").height()), (800, 456))

    def test_tasks_survive_collapse_and_expand(self) -> None:
        self.expand()
        store = self.find("calendarTasks").property("taskStore")
        store.addTask("保留任务")
        self.hover_outside()
        QTest.qWait(700)
        self.assertTrue(self.window.property("compact"))

        self.expand()
        self.assertEqual([task.title for task in store.tasks], ["保留任务"])


if __name__ == "__main__":
    unittest.main()
