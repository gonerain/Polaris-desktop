"""Real pointer/keyboard regression coverage for the schedule's owned Qt view."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

if __name__ != '__main__':
    class ScheduleUIProcessTests(unittest.TestCase):
        def test_schedule_interactions(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import tempfile
    from PySide6.QtCore import QPoint, QPointF, Qt, QUrl, QEvent, QCoreApplication
    from PySide6.QtGui import QGuiApplication, QCursor, QKeyEvent
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest
    import shiboken6
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    sys.path.insert(0, str(ROOT / 'components' / 'schedule'))
    from polaris_schedule import Schedule

    def find(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = find(child, name)
            if found is not None:
                return found
        return None

    class ScheduleInteractions(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.directory = tempfile.TemporaryDirectory()
            self.runtime = build(default_config())
            self.runtime.install({'id': 'user', 'name': 'User', 'version': '1', 'platformApi': 1,
                                  'entry': {'mode': 'inprocess'}}, Component)
            self.runtime.start_component('user')
            self.manifest = {'id': 'org.polaris.schedule', 'name': 'Schedule', 'version': '1', 'platformApi': 1,
                             'entry': {'mode': 'inprocess'}}
            self.component = Schedule(self.directory.name)
            self.runtime.install(self.manifest, lambda: self.component)
            self.runtime.start_component('org.polaris.schedule')
            for operation in self.runtime.status('org.polaris.schedule')['description']['operations']:
                self.runtime.grant('user', 'org.polaris.schedule', operation)
            self.context = self.runtime.user_context('user')
            source = Path(self.directory.name) / 'root.qml'
            source.write_text("import QtQuick\nRectangle { width: 780; height: 620; color: '#f8faff' }\n")
            self.window = QQuickView()
            self.window.setSource(QUrl.fromLocalFile(str(source)))
            self.window.resize(780, 620)
            self.window.show()
            self.resource = self.call('create_view', {'view': 'main', 'parent': self.window.rootObject()})
            self.item = self.resource['item']
            self.item.setWidth(780)
            self.item.setHeight(620)
            QTest.qWait(80)

        def tearDown(self):
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'])
            self.window.close()
            shiboken6.delete(self.window)
            self.app.processEvents()
            self.directory.cleanup()

        def call(self, operation, params=None):
            return self.runtime.client('user').call('org.polaris.schedule', operation, params, context=self.context)

        def control(self, name):
            result = find(self.window.contentItem(), name)
            self.assertIsNotNone(result, name)
            return result

        def click(self, target):
            item = self.control(target) if isinstance(target, str) else target
            point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
            point = QPoint(round(point.x()), round(point.y()))
            QCursor.setPos(self.window.mapToGlobal(point))
            QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
            QTest.qWait(35)

        def type(self, name, value):
            self.click(name)
            QTest.keyClick(self.window, Qt.Key_A, Qt.ControlModifier)
            for char in value:
                QCoreApplication.sendEvent(self.window, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, char))
                QCoreApplication.sendEvent(self.window, QKeyEvent(QEvent.KeyRelease, 0, Qt.NoModifier, char))
            QTest.qWait(20)

        def test_day_rollover_follows_today_but_keeps_explicit_browsing(self):
            self.item.setProperty('todayDate', '2026-10-31')
            self.item.setProperty('selectedDate', '2026-10-31')
            self.item.refreshToday('2026-11-01')
            self.assertEqual(self.item.property('selectedDate'), '2026-11-01')
            self.item.setProperty('selectedDate', '2026-12-25')
            self.item.refreshToday('2026-11-02')
            self.assertEqual(self.item.property('selectedDate'), '2026-12-25')
            self.item.setWidth(370)
            self.item.setHeight(220)
            self.assertTrue(self.control('todayButton').property('visible'))

        def test_crud_editor_subtask_restart_and_revocation(self):
            self.type('quickAdd', '<b>Planning</b>')
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(40)
            task = self.call('get')['tasks'][0]
            self.assertEqual(task['title'], '<b>Planning</b>')
            self.click('importantTask_0')
            self.assertTrue(self.call('get')['tasks'][0]['important'])
            # Open through the visible task row, outside the completion/star buttons.
            row = self.control('completeTask_0').parentItem()
            point = row.mapToScene(QPointF(150, 18))
            QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(50)
            self.type('taskTitle', 'Planning revised')
            self.type('taskTime', '09:30')
            self.type('taskNotes', 'Release checklist')
            self.type('subtaskInput', 'Review patch')
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(40)
            self.assertEqual(self.call('get')['tasks'][0]['subtasks'][0]['title'], 'Review patch')
            self.type('subtaskTitle_0', 'Review revised patch')
            self.click('completeSubtask_0')
            self.window.grabWindow().save('/tmp/polaris-schedule-editor.png')
            self.runtime.revoke('user', 'org.polaris.schedule', 'update')
            self.click('saveTask')
            self.assertEqual(self.control('taskTitle').property('text'), 'Planning revised')
            self.runtime.grant('user', 'org.polaris.schedule', 'update')
            self.click('saveTask')
            task = self.call('get')['tasks'][0]
            self.assertEqual((task['title'], task['time'], task['notes']), ('Planning revised', '09:30', 'Release checklist'))
            self.assertTrue(task['subtasks'][0]['done'])
            self.assertEqual(task['subtasks'][0]['title'], 'Review revised patch')
            self.assertEqual(Schedule(self.directory.name).store.tasks()[0], task)
            self.window.grabWindow().save('/tmp/polaris-schedule-wide.png')
            self.item.setWidth(370); self.item.setHeight(220)
            self.window.resize(370, 220)
            QTest.qWait(60)
            self.window.grabWindow().save('/tmp/polaris-schedule-compact.png')
            self.runtime.revoke('user', 'org.polaris.schedule', 'add')
            self.type('quickAdd', 'Keep this draft')
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(40)
            self.assertEqual(self.control('quickAdd').property('text'), 'Keep this draft')
            self.assertEqual(len(self.call('get')['tasks']), 1)
            self.runtime.grant('user', 'org.polaris.schedule', 'add')
            self.click('addTask')
            self.assertEqual(len(self.call('get')['tasks']), 2)
            # Delete through the compact editor and undo through the card.
            row = self.control('completeTask_0').parentItem()
            point = row.mapToScene(QPointF(150, 18))
            QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(40)
            self.click('deleteTask')
            self.assertEqual(len(self.call('get')['tasks']), 1)
            self.click('undoDelete')
            self.assertEqual(len(self.call('get')['tasks']), 2)
            self.click('completeTask_0')
            self.assertTrue(any(t['done'] for t in self.call('get')['tasks']))

        def test_failed_parent_error_survives_queued_child_refresh(self):
            self.type('quickAdd', 'Parent task')
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(40)
            task = self.call('get')['tasks'][0]
            self.call('add_subtask', {'identity': task['id'], 'title': 'Original child'})
            QTest.qWait(40)
            row = self.control('completeTask_0').parentItem()
            point = row.mapToScene(QPointF(150, 18))
            QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(40)
            self.type('taskTitle', '')
            QTest.keyClick(self.window, Qt.Key_Backspace)
            self.type('subtaskTitle_0', 'Child before failed save')
            # Enter commits the child and queues a cross-view refresh. Save the
            # invalid parent before processing that refresh's event delivery.
            QTest.keyClick(self.window, Qt.Key_Return)
            self.click('saveTask')
            QTest.qWait(100)
            self.assertIn('标题不能为空', self.control('editorError').property('text'))
            self.assertEqual(self.control('taskTitle').property('text'), '')
            self.assertEqual(self.call('get')['tasks'][0]['title'], 'Parent task')
            self.type('taskTitle', 'Parent revised')
            self.type('taskDate', '2026-02-30')
            self.type('subtaskTitle_0', 'Child before invalid date')
            QTest.keyClick(self.window, Qt.Key_Return)
            self.click('saveTask')
            QTest.qWait(100)
            self.assertIn('日期', self.control('editorError').property('text'))
            self.assertEqual(self.control('taskTitle').property('text'), 'Parent revised')
            self.assertEqual(self.control('taskDate').property('text'), '2026-02-30')
            self.assertEqual(self.call('get')['tasks'][0]['title'], 'Parent task')

        def test_overdue_scope_and_subtask_notes_search(self):
            self.call('add', {'title': 'Inbox', 'date': None})
            past = self.call('add', {'title': 'Overdue', 'date': '2001-01-01'})
            finished = self.call('add', {'title': 'Finished', 'date': '2001-01-01'})
            self.call('update', {'identity': finished['id'], 'done': True})
            child = self.call('add_subtask', {'identity': past['id'], 'title': 'Checklist'})
            self.call('update_subtask', {'parent_id': past['id'], 'subtask_id': child['id'], 'notes': 'buried keyword'})
            QTest.qWait(60)
            self.click('scheduleSections')
            self.click('section_4')
            self.assertEqual(self.control('taskList').property('count'), 1)
            self.click('scheduleSections')
            self.click('section_1')
            self.assertEqual(self.control('taskList').property('count'), 1)
            self.click('searchButton')
            self.type('scheduleSearch', 'buried keyword')
            self.assertEqual(self.control('taskList').property('count'), 1)
            self.click('searchButton')
            self.assertEqual(self.control('taskList').property('count'), 1)

        def test_search_planner_and_permission_boundaries(self):
            for title in ('Draft proposal', 'Review design', 'Publish notes'):
                self.type('quickAdd', title)
                QTest.keyClick(self.window, Qt.Key_Return)
                QTest.qWait(40)
            for title in ('Prepare agenda', 'Team meeting'):
                self.click('nextDay')
                self.type('quickAdd', title)
                QTest.keyClick(self.window, Qt.Key_Return)
                QTest.qWait(40)
            self.click('previousDay')
            self.click('previousDay')
            self.click('searchButton')
            self.type('scheduleSearch', 'Review')
            self.assertEqual(self.control('taskList').property('count'), 1)
            self.click('searchButton')
            self.click('scheduleModes')
            self.click('mode_1')
            self.window.grabWindow().save('/tmp/polaris-schedule-week.png')
            self.click('scheduleModes')
            self.click('mode_2')
            self.click('selectedDay')
            self.type('dayInput', '2026-01-31')
            self.click('chooseDay')
            self.click('nextDay')
            self.assertEqual(self.item.property('selectedDate'), '2026-02-28')
            self.click('selectedDay')
            self.type('dayInput', '2026-02-30')
            self.click('chooseDay')
            self.assertEqual(self.item.property('selectedDate'), '2026-02-28')
            QTest.keyClick(self.window, Qt.Key_Escape)
            self.click('selectedDay')
            from datetime import date
            self.type('dayInput', date.today().isoformat())
            self.click('chooseDay')
            self.window.grabWindow().save('/tmp/polaris-schedule-month.png')
            self.click('scheduleModes')
            self.click('mode_0')
            self.click('scheduleSections')
            self.click('section_1')
            self.type('quickAdd', 'Inbox task')
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(40)
            self.assertEqual(self.control('taskList').property('count'), 1)
            self.assertIsNone(self.call('get')['tasks'][-1]['date'])
            self.click('searchButton')
            self.type('scheduleSearch', 'Review')
            self.assertEqual(self.control('taskList').property('count'), 1)
            self.click('searchButton')
            # A business write succeeds even when its subsequent read is revoked.
            before = len(self.component.store.tasks())
            self.runtime.revoke('user', 'org.polaris.schedule', 'get')
            self.type('quickAdd', 'Accepted once')
            QTest.keyClick(self.window, Qt.Key_Return)
            QTest.qWait(60)
            self.assertEqual(self.control('quickAdd').property('text'), '')
            self.assertEqual(len(self.component.store.tasks()), before + 1)
            self.assertEqual(self.control('taskList').property('count'), 0)
            bridge = self.component._presentation._views[self.resource['handle']][2]
            self.assertTrue(bridge.lastError)
            self.runtime.grant('user', 'org.polaris.schedule', 'get')
            self.assertTrue(bridge.refresh())
            self.call('release_view', {'handle': self.resource['handle']})
            QTest.qWait(40)
            self.assertEqual(len(self.call('get')['tasks']), before + 1)
            self.assertFalse(self.window.rootObject().childItems())
            replacement = self.call('create_view', {'view': 'main', 'parent': self.window.rootObject()})
            self.assertIsNotNone(replacement['item'])
            self.runtime.stop_component('org.polaris.schedule')
            QTest.qWait(40)
            self.assertFalse(self.window.rootObject().childItems())

    unittest.main()
