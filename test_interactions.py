"""联动规则与桌宠气泡，仅在离屏软件渲染环境测试。"""

from datetime import date, datetime

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest

from headless_test_support import HeadlessQtTestCase, find_visual_item
from main import create_engine
from polaris.interactions import InteractionCoordinator
from polaris.tasks import CalendarTaskStore


class InteractionTests(HeadlessQtTestCase):
    def test_upcoming_in_any_date_and_no_duplicate_after_navigation(self):
        current = [datetime(2024, 1, 31, 8, 59)]
        store = CalendarTaskStore(today=date(2024, 1, 31))
        coordinator = InteractionCoordinator(clock=lambda: current[0])
        spy = QSignalSpy(coordinator.notification)
        coordinator.attach(store)
        task = store.addTask("晨会", "09:10")
        self.assertEqual(spy.count(), 0)
        store.selectDate("2024-02-01")
        current[0] = datetime(2024, 1, 31, 9, 0)
        coordinator.check()
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0), ["task.upcoming", task.entryId, "10 分钟后 · 晨会"])
        coordinator.check()
        store.selectDate("2024-01-31")
        task.setDone(True)
        task.setDone(False)
        self.assertEqual(spy.count(), 1)

    def test_edits_and_completed_or_all_day_tasks(self):
        current = [datetime(2024, 1, 31, 9, 5)]
        store = CalendarTaskStore(today=date(2024, 1, 31))
        coordinator = InteractionCoordinator(clock=lambda: current[0])
        spy = QSignalSpy(coordinator.notification)
        coordinator.attach(store)
        store.addTask("全天")
        done = store.addTask("完成", "09:09")
        done.setDone(True)
        self.assertEqual(spy.count(), 1)  # 新增时仍未完成，立刻提醒一次
        self.assertTrue(store.removeTask(done.entryId))
        late = store.addTask("已过期", "09:04")
        self.assertEqual(spy.count(), 1)
        late.setTime("09:08")
        self.assertEqual(spy.count(), 2)
        self.assertEqual(spy.at(1)[2], "3 分钟后 · 已过期")
        late.setTime("09:09")
        self.assertEqual(spy.count(), 3)
        late.setTime("09:08")
        self.assertEqual(spy.count(), 4)  # 换时间后新提醒周期
        current[0] = datetime(2024, 1, 31, 9, 10)
        coordinator.check()
        self.assertEqual(spy.count(), 4)

    def test_completed_task_stays_silent_until_rescheduled(self):
        current = [datetime(2024, 1, 31, 8, 0)]
        store = CalendarTaskStore(today=date(2024, 1, 31))
        coordinator = InteractionCoordinator(clock=lambda: current[0])
        spy = QSignalSpy(coordinator.notification)
        coordinator.attach(store)
        task = store.addTask("整理", "09:10")
        task.setDone(True)
        current[0] = datetime(2024, 1, 31, 9, 0)
        coordinator.check()
        self.assertEqual(spy.count(), 0)
        task.setDone(False)
        self.assertEqual(spy.count(), 1)
        task.rename("整理资料")
        self.assertEqual(spy.count(), 1)
        self.assertTrue(store.removeTask(task.entryId))
        self.assertEqual(spy.count(), 1)

    def test_compact_bubble_and_expand_restore_geometry(self):
        engine = create_engine()
        window = engine.rootObjects()[0]
        self.addCleanup(self.close_engine, engine, window)
        self.assertTrue(QTest.qWaitForWindowExposed(window, 3000))
        coordinator = window.findChild(QObject, "interactionCoordinator")
        pet = find_visual_item(window.contentItem(), "compactBox")
        bubble = find_visual_item(window.contentItem(), "petSpeechBubble")
        y = window.y()
        coordinator.notification.emit("task.upcoming", 1, "10 分钟后 · 晨会")
        self.app.processEvents()
        self.assertTrue(bubble.isVisible())
        self.assertEqual(window.height(), 238)
        self.assertEqual(window.y(), y - 58)
        coordinator.notification.emit("task.upcoming", 2, "5 分钟后 · 评审")
        self.assertEqual(window.height(), 238)
        self.assertEqual(window.property("bubbleText"), "5 分钟后 · 评审")
        point = pet.mapToScene(QPointF(90, 90)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, pos=point)
        self.app.processEvents()
        self.assertFalse(window.property("compact"))
        self.assertFalse(bubble.isVisible())
        self.assertEqual(window.y(), y)
        self.assertEqual(window.height(), 300)
        coordinator.notification.emit("task.upcoming", 3, "明天 · 回顾")
        self.assertFalse(bubble.isVisible())
        self.assertEqual(window.height(), 300)
