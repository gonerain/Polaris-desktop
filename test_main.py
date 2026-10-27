"""主窗口的离屏软件渲染测试，不连接真实桌面。"""

import os
import unittest

# 必须在创建 Qt 应用前隔离显示服务，禁止测试影响真实桌面。
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ.pop("DISPLAY", None)
os.environ.pop("WAYLAND_DISPLAY", None)

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt, SIGNAL
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QSignalSpy, QTest

from main import create_engine


def find_visual_item(parent, name):
    if parent.objectName() == name:
        return parent
    for child in parent.childItems():
        found = find_visual_item(child, name)
        if found is not None:
            return found
    return None


class MainWindowTests(unittest.TestCase):
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
        self.click("compactBox")
        QTest.qWait(300)
        self.assertFalse(self.window.property("compact"))
        self.board = self.find("componentBoard")
        self.calendar = self.find("calendarTasks")
        self.title_bar = self.find("titleBar")
        self.store = self.calendar.property("taskStore")
        self.assertIsNotNone(self.store)

    def close_window(self) -> None:
        self.window.close()
        self.engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def find(self, name: str):
        result = find_visual_item(self.window.contentItem(), name)
        self.assertIsNotNone(result, name)
        return result

    def click(self, name: str) -> None:
        QTest.qWait(25)
        item = self.find(name)
        position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, pos=position.toPoint())
        self.app.processEvents()
        QTest.qWait(200)

    def open_calendar(self) -> None:
        if not self.calendar.property("calendarVisible"):
            self.click("openCalendarButton")
        self.assertTrue(self.calendar.property("calendarVisible"))

    def close_calendar(self) -> None:
        if self.calendar.property("calendarVisible"):
            self.click("closeCalendarButton")
        self.assertFalse(self.calendar.property("calendarVisible"))

    def open_composer(self) -> None:
        if not self.find("newTaskInput").isVisible():
            self.click("openComposerButton")
        self.assertTrue(self.find("newTaskInput").isVisible())

    def day_item(self):
        return self.find("calendarDay" + self.store.property("selectedDate"))

    def test_rendering_is_isolated_from_the_desktop(self) -> None:
        self.assertEqual(self.app.platformName(), "offscreen")
        self.assertEqual(QQuickWindow.sceneGraphBackend(), "software")
        self.assertNotIn("DISPLAY", os.environ)
        self.assertNotIn("WAYLAND_DISPLAY", os.environ)

    def test_title_drag_gesture_activates_in_offscreen_scene(self) -> None:
        handler = self.window.findChild(QObject, "windowMoveHandler")
        self.assertIsNotNone(handler)
        changes = QSignalSpy(handler, SIGNAL("activeChanged()"))
        QTest.mousePress(self.window, Qt.MouseButton.LeftButton, pos=QPoint(60, 20))
        try:
            QTest.mouseMove(self.window, QPoint(120, 20), 20)
            self.assertTrue(handler.property("active"))
        finally:
            QTest.mouseRelease(self.window, Qt.MouseButton.LeftButton, pos=QPoint(120, 20))
        self.assertFalse(handler.property("active"))
        self.assertGreaterEqual(changes.count(), 2)

    def test_resize_handles_receive_local_pointer_events(self) -> None:
        resize_handles = self.find("resizeHandles")
        handles_by_name = {item.objectName(): item for item in resize_handles.childItems()}
        width, height = self.window.width(), self.window.height()
        regions = [
            (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, QPoint(2, 2)),
            (Qt.Edge.TopEdge, QPoint(width // 2, 2)),
            (Qt.Edge.TopEdge | Qt.Edge.RightEdge, QPoint(width - 2, 2)),
            (Qt.Edge.LeftEdge, QPoint(2, height // 2)),
            (Qt.Edge.RightEdge, QPoint(width - 2, height // 2)),
            (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, QPoint(2, height - 2)),
            (Qt.Edge.BottomEdge, QPoint(width // 2, height - 2)),
            (Qt.Edge.BottomEdge | Qt.Edge.RightEdge, QPoint(width - 2, height - 2)),
        ]
        for edges, position in regions:
            with self.subTest(edges=edges):
                handle = handles_by_name.get(f"resizeHandle{edges.value}")
                self.assertIsNotNone(handle)
                QTest.mousePress(self.window, Qt.MouseButton.LeftButton, pos=position)
                try:
                    self.assertTrue(handle.property("pressed"))
                finally:
                    QTest.mouseRelease(self.window, Qt.MouseButton.LeftButton, pos=position)
                self.assertFalse(handle.property("pressed"))

    def test_window_has_no_system_frame(self) -> None:
        self.assertTrue(self.window.flags() & Qt.WindowType.FramelessWindowHint)

    def test_window_stays_on_top(self) -> None:
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.flags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_default_board_uses_exactly_two_panels_for_the_calendar(self) -> None:
        self.assertEqual(self.board.property("panelCount"), 2)
        self.assertEqual(self.board.property("freePanelCount"), 0)
        self.assertEqual(self.board.property("columns"), 2)
        self.assertEqual(self.board.property("rows"), 1)
        self.assertAlmostEqual(self.board.property("cellWidth"), 260.0)
        self.assertAlmostEqual(self.board.property("cellHeight"), 256.0)
        self.assertEqual(self.calendar.width(), self.window.width())
        self.assertEqual(self.calendar.height(), self.window.height() - self.title_bar.height())
        self.assertFalse(self.calendar.property("calendarVisible"))
        self.assertTrue(self.find("openCalendarButton").isVisible())
        self.assertTrue(self.find("openComposerButton").isVisible())
        self.assertIsNone(self.window.findChild(QQuickItem, "editor"))

    def test_calendar_panels_grow_with_the_window(self) -> None:
        self.open_calendar()
        day = self.day_item()
        initial_day_width, initial_day_height = day.width(), day.height()
        self.close_calendar()
        self.open_composer()
        initial_task_width = self.find("newTaskInput").width()

        self.window.resize(1000, 600)
        self.app.processEvents()
        QTest.qWait(100)

        self.assertEqual((self.board.width(), self.board.height()), (1000, 556))
        self.assertAlmostEqual(self.board.property("cellWidth"), 496.0)
        self.assertAlmostEqual(self.board.property("cellHeight"), 556.0)
        self.assertEqual((self.calendar.width(), self.calendar.height()), (1000, 556))
        self.assertGreater(self.find("newTaskInput").width(), initial_task_width)

        self.open_calendar()
        day = self.day_item()
        self.assertGreater(day.width(), initial_day_width)
        self.assertGreater(day.height(), initial_day_height)

    def test_calendar_remains_editable_after_resize(self) -> None:
        self.window.resize(900, 520)
        self.app.processEvents()
        QTest.qWait(100)

        initial_date = self.store.property("selectedDate")
        self.open_calendar()
        self.click("nextMonthButton")
        self.assertNotEqual(self.store.property("selectedDate"), initial_date)
        self.close_calendar()

        self.open_composer()
        self.find("newTaskInput").setProperty("text", "放大后任务")
        self.click("addTaskButton")
        self.assertIn("放大后任务", [task.title for task in self.store.tasks])

    def test_minimum_size_keeps_two_base_panels(self) -> None:
        self.assertEqual(self.window.minimumWidth(), 528)
        self.assertEqual(self.window.minimumHeight(), 300)

    def test_minimize_button_preserves_tasks_after_restore(self) -> None:
        self.store.addTask("最小化后保留")
        self.click("minimizeButton")
        self.assertEqual(self.window.visibility(), QWindow.Visibility.Minimized)
        self.window.showNormal()
        self.assertTrue(QTest.qWaitForWindowExposed(self.window, 3000))
        self.assertEqual([task.title for task in self.store.tasks], ["最小化后保留"])
        self.assertTrue(self.window.flags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_close_button_closes_window(self) -> None:
        self.click("closeButton")
        self.assertFalse(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
