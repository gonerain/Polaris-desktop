from datetime import date
import unittest

from headless_test_support import HeadlessQtTestCase
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from polaris.tasks import CalendarTaskStore


class CalendarStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = CalendarTaskStore(today=date(2024, 1, 31))

    def test_month_navigation_and_leap_year(self):
        self.assertTrue(self.store.changeMonth(1))
        self.assertEqual(self.store.selectedDate, '2024-02-29')
        self.assertEqual(len(self.store.calendarCells), 42)
        self.assertEqual(self.store.calendarCells[0]['date'], '2024-01-29')
        self.assertEqual(sum(c['inMonth'] for c in self.store.calendarCells), 29)
        self.assertEqual(sum(c['selected'] for c in self.store.calendarCells), 1)
        self.assertTrue(self.store.selectDate('2023-01-31'))
        self.store.changeMonth(1)
        self.assertEqual(self.store.selectedDate, '2023-02-28')
        self.assertFalse(self.store.selectDate('2023-02-29'))
        self.assertFalse(self.store.changeMonth(-1000000))

    def test_tasks_are_per_date_and_renames_preserve_instances(self):
        task = self.store.addTask('  写方案  ')
        self.assertEqual(task.title, '写方案')
        self.assertTrue(task.rename('修改方案'))
        self.assertIs(self.store.tasks[0], task)
        self.store.selectDate('2024-02-01')
        self.assertEqual(self.store.tasks, [])
        self.store.selectDate('2024-01-31')
        self.assertIs(self.store.tasks[0], task)
        self.assertEqual(task.title, '修改方案')
        self.assertTrue(self.store.removeTask(task.entryId))
        self.assertFalse(self.store.removeTask(task.entryId))
        self.assertEqual(self.store.tasks, [])

    def test_subtasks_can_be_added_renamed_and_deleted(self):
        task = self.store.addTask('准备会议')
        child = task.addSubtask('整理材料')
        self.assertTrue(child.rename('整理新材料'))
        self.assertEqual(task.subtasks[0].title, '整理新材料')
        self.assertIsNone(child.addSubtask('不创建第二级子任务'))
        self.assertNotEqual(task.entryId, child.entryId)
        self.assertTrue(task.removeSubtask(child.entryId))
        self.assertFalse(task.removeSubtask(child.entryId))
        self.assertEqual(task.subtasks, [])

    def test_calendar_date_limits_do_not_overflow(self):
        for selected in ('0001-01-01', '9999-12-31'):
            self.assertTrue(self.store.selectDate(selected))
            self.assertEqual(len(self.store.calendarCells), 42)
            self.assertEqual(sum(cell['selected'] for cell in self.store.calendarCells), 1)
        self.assertFalse(self.store.changeMonth(1))

    def test_empty_titles_are_rejected_and_no_data_is_persisted(self):
        self.assertIsNone(self.store.addTask('  '))
        task = self.store.addTask('任务')
        self.assertFalse(task.rename(''))
        self.assertIsNone(task.addSubtask('\n'))
        self.assertEqual(task.title, '任务')
        self.assertEqual(CalendarTaskStore(today=date(2024, 1, 31)).tasks, [])


class CalendarWidgetTests(HeadlessQtTestCase):
    def setUp(self):
        self.window = self.load_window('''
import QtQuick
import "components"
Window {
    width: 528; height: 260; visible: true
    ComponentBoard {
        id: board; anchors.fill: parent
        panelSize: Qt.size(260, 260); panelCount: 2; gap: 8
    }
    Component { id: factory; CalendarTasks { objectName: "calendarTasks" } }
    Component.onCompleted: board.request(factory, {cells: [[0,0],[1,0]]})
}
''')
        self.widget = self.item(self.window, 'calendarTasks')
        self.store = self.widget.property('taskStore')
        self.store.selectDate('2024-02-29')
        self.app.processEvents()

    def click(self, name):
        QTest.qWait(25)
        item = self.item(self.window, name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, pos=point)
        self.app.processEvents()

    def test_calendar_and_two_panel_dimensions(self):
        self.assertEqual((self.widget.width(), self.widget.height()), (528, 260))
        self.click('nextMonthButton')
        self.assertEqual(self.store.selectedDate, '2024-03-29')
        self.click('previousMonthButton')
        self.assertEqual(self.store.selectedDate, '2024-02-29')
        self.click('calendarDay2024-02-14')
        self.assertEqual(self.store.selectedDate, '2024-02-14')

    def test_edit_tasks_and_subtasks_through_the_widget(self):
        self.item(self.window, 'newTaskInput').setProperty('text', '制定计划')
        self.click('addTaskButton')
        self.assertEqual(len(self.store.tasks), 1)
        task = self.store.tasks[0]
        self.item(self.window, f'newSubtaskInput{task.entryId}').setProperty('text', '收集资料')
        self.click(f'addSubtask{task.entryId}')
        self.assertEqual(len(task.subtasks), 1)
        child = task.subtasks[0]
        field = self.item(self.window, f'subtaskTitle{child.entryId}')
        field.forceActiveFocus()
        field.setProperty('text', '更新资料')
        QTest.keyClick(self.window, Qt.Key_Return)
        self.assertEqual(child.title, '更新资料')
        field = self.item(self.window, f'taskTitle{task.entryId}')
        field.forceActiveFocus()
        field.setProperty('text', '更新计划')
        QTest.keyClick(self.window, Qt.Key_Return)
        self.assertEqual(task.title, '更新计划')
        self.click(f'removeSubtask{child.entryId}')
        self.assertEqual(task.subtasks, [])
        self.click(f'removeTask{task.entryId}')
        self.assertEqual(self.store.tasks, [])
