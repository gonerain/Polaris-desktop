from datetime import date
import unittest

from headless_test_support import HeadlessQtTestCase
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from polaris.tasks import CalendarTaskStore, clean_time


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

    def test_times_are_validated_normalized_and_sorted(self):
        self.assertEqual(clean_time(None), '')
        self.assertEqual(clean_time(' 9:5 '), '09:05')
        self.assertEqual(clean_time('12：30'), '12:30')
        self.assertIsNone(clean_time('24:00'))
        self.assertIsNone(clean_time('9:60'))

        all_day = self.store.addTask('全天任务')
        late = self.store.addTask('晚间任务', '18:05')
        early = self.store.addTask('晨间任务', '9:00')
        self.assertEqual(early.time, '09:00')
        self.assertEqual([task.title for task in self.store.tasks], ['全天任务', '晨间任务', '晚间任务'])
        self.assertIsNone(self.store.addTask('非法时间', '25:00'))
        self.assertFalse(early.setTime('12:99'))
        self.assertTrue(early.setTime('10:15'))
        self.assertEqual([task.title for task in self.store.tasks], ['全天任务', '晨间任务', '晚间任务'])
        self.assertEqual(all_day.time, '')
        self.assertEqual(late.time, '18:05')

    def test_completion_and_subtask_progress(self):
        task = self.store.addTask('准备发布', '09:00')
        child = task.addSubtask('检查清单')
        second = task.addSubtask('通知团队')
        self.assertEqual((task.subtaskCount, task.completedSubtaskCount), (2, 0))
        child.setDone(True)
        self.assertEqual((task.subtaskCount, task.completedSubtaskCount), (2, 1))
        self.assertFalse(task.done)
        self.assertTrue(task.setDone(True))
        self.assertEqual(self.store.completedCount, 1)
        cell = next(cell for cell in self.store.calendarCells if cell['date'] == '2024-01-31')
        self.assertEqual((cell['taskCount'], cell['openCount']), (1, 0))
        task.setDone(False)
        cell = next(cell for cell in self.store.calendarCells if cell['date'] == '2024-01-31')
        self.assertEqual((cell['taskCount'], cell['openCount']), (1, 1))
        second.setDone(True)
        self.assertEqual(task.completedSubtaskCount, 2)

    def test_selected_date_text_and_today(self):
        self.store.selectDate('2024-02-29')
        self.assertEqual(self.store.selectedDateLabel, '2月29日')
        self.assertEqual(self.store.selectedWeekday, '周四')
        self.assertEqual(self.store.selectedDayNumber, 29)
        self.assertTrue(self.store.goToday())
        self.assertEqual(self.store.selectedDate, '2024-01-31')
        self.assertFalse(self.store.isValidTime('12:60'))
        self.assertTrue(self.store.isValidTime('7:05'))


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
        QTest.qWait(220)

    def open_composer(self):
        if not self.item(self.window, 'newTaskInput').isVisible():
            self.click('openComposerButton')
        self.assertTrue(self.item(self.window, 'newTaskInput').isVisible())

    def open_calendar(self):
        if not self.widget.property('calendarVisible'):
            self.click('openCalendarButton')
        self.assertTrue(self.widget.property('calendarVisible'))

    def test_minimal_default_state_leaves_only_a_plus(self):
        self.assertFalse(self.widget.property('calendarVisible'))
        self.assertFalse(self.item(self.window, 'calendarMonthView').isVisible())
        self.assertTrue(self.item(self.window, 'agendaPanel').isVisible())
        self.assertTrue(self.item(self.window, 'openCalendarButton').isVisible())
        self.assertTrue(self.item(self.window, 'openComposerButton').isVisible())
        self.assertFalse(self.item(self.window, 'newTaskInput').isVisible())
        self.assertEqual(self.store.tasks, [])

    def test_calendar_is_hidden_by_default_and_returns_after_a_date(self):
        self.assertEqual((self.widget.width(), self.widget.height()), (528, 260))
        self.assertFalse(self.widget.property('calendarVisible'))
        self.assertFalse(self.item(self.window, 'calendarMonthView').isVisible())
        self.assertTrue(self.item(self.window, 'agendaPanel').isVisible())

        self.open_calendar()
        self.assertTrue(self.item(self.window, 'calendarMonthView').isVisible())
        self.click('nextMonthButton')
        self.assertEqual(self.store.selectedDate, '2024-03-29')
        self.click('previousMonthButton')
        self.assertEqual(self.store.selectedDate, '2024-02-29')
        self.click('calendarDay2024-02-14')
        self.assertEqual(self.store.selectedDate, '2024-02-14')
        self.assertFalse(self.widget.property('calendarVisible'))
        self.assertTrue(self.item(self.window, 'agendaPanel').isVisible())

        self.open_calendar()
        self.click('todayButton')
        self.assertEqual(self.store.selectedDate, date.today().isoformat())
        self.assertFalse(self.widget.property('calendarVisible'))

    def test_edit_tasks_and_subtasks_through_the_widget(self):
        self.open_composer()
        self.item(self.window, 'newTaskTimeInput').setProperty('text', '9:15')
        self.item(self.window, 'newTaskInput').setProperty('text', '制定计划')
        self.click('addTaskButton')
        self.assertEqual(len(self.store.tasks), 1)
        task = self.store.tasks[0]
        self.assertEqual(task.time, '09:15')

        self.click(f'addSubtaskLink{task.entryId}')
        self.item(self.window, f'newSubtaskInput{task.entryId}').setProperty('text', '收集资料')
        self.click(f'addSubtask{task.entryId}')
        self.assertEqual(len(task.subtasks), 1)
        child = task.subtasks[0]

        self.click(f'toggleSubtask{child.entryId}')
        self.assertTrue(child.done)
        self.assertEqual(task.completedSubtaskCount, 1)

        field = self.item(self.window, f'subtaskTitle{child.entryId}')
        field.forceActiveFocus()
        field.setProperty('text', '更新资料')
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(100)
        self.assertEqual(child.title, '更新资料')

        field = self.item(self.window, f'taskTitle{task.entryId}')
        field.forceActiveFocus()
        field.setProperty('text', '更新计划')
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(100)
        self.assertEqual(task.title, '更新计划')

        time_field = self.item(self.window, f'taskTime{task.entryId}')
        time_field.forceActiveFocus()
        time_field.setProperty('text', '11:45')
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(100)
        self.assertEqual(task.time, '11:45')

        self.click(f'toggleTask{task.entryId}')
        self.assertTrue(task.done)
        self.click(f'removeSubtask{child.entryId}')
        self.assertEqual(task.subtasks, [])
        self.click(f'removeTask{task.entryId}')
        self.assertEqual(self.store.tasks, [])

    def test_invalid_time_is_rejected(self):
        self.open_composer()
        self.item(self.window, 'newTaskTimeInput').setProperty('text', '25:99')
        self.item(self.window, 'newTaskInput').setProperty('text', '非法时间任务')
        self.click('addTaskButton')
        self.assertEqual(self.store.tasks, [])
        self.assertTrue(self.item(self.window, 'newTaskTimeInput').property('error'))
        self.assertTrue(self.item(self.window, 'newTaskInput').isVisible())

    def test_new_task_entrance_animation_is_scoped(self):
        first = self.store.addTask('先添加')
        QTest.qWait(250)
        second = self.store.addTask('后添加')
        QTest.qWait(60)

        first_card = self.item(self.window, f'taskCard{first.entryId}')
        second_card = self.item(self.window, f'taskCard{second.entryId}')
        self.assertFalse(first_card.property('animateEntrance'))
        self.assertTrue(second_card.property('animateEntrance'))
        self.assertEqual(first_card.opacity(), 1.0)

        QTest.qWait(550)
        second_card = self.item(self.window, f'taskCard{second.entryId}')
        self.assertFalse(second_card.property('animateEntrance'))

    def test_task_time_can_be_edited_and_invalid_time_is_reverted(self):
        task = self.store.addTask('调整时间', '09:00')
        QTest.qWait(250)
        field = self.item(self.window, f'taskTime{task.entryId}')
        field.forceActiveFocus()
        field.setProperty('text', '23:70')
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(120)
        self.assertEqual(task.time, '09:00')
        self.assertTrue(field.property('error'))

        field.setProperty('text', '15:20')
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.qWait(150)
        self.assertEqual(task.time, '15:20')
        self.assertFalse(field.property('error'))

    def test_subtasks_can_be_collapsed(self):
        task = self.store.addTask('带子任务')
        task.addSubtask('第一步')
        task.addSubtask('第二步')
        QTest.qWait(250)
        wrapper = self.item(self.window, f'subtaskWrapper{task.entryId}')
        self.assertFalse(wrapper.isVisible())

        self.click(f'toggleSubtasks{task.entryId}')
        self.assertTrue(wrapper.isVisible())
        self.assertGreater(wrapper.height(), 0)

        self.click(f'toggleSubtasks{task.entryId}')
        QTest.qWait(350)
        self.assertFalse(wrapper.isVisible())
        self.assertLess(wrapper.height(), 1)
