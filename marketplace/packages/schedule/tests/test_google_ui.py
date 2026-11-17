"""Native Qt tests for Google Calendar presentation (skip without PySide6)."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

try:
    from PySide6.QtCore import QUrl, QObject, QMetaObject, Qt, qInstallMessageHandler, QTimer, QEventLoop
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView
    from shiboken6 import delete

    class QTest:
        @staticmethod
        def qWait(milliseconds):
            loop = QEventLoop()
            QTimer.singleShot(milliseconds, loop.quit)
            loop.exec()
except ImportError:
    QGuiApplication = None

from polaris_schedule import Schedule


@unittest.skipIf(QGuiApplication is None, 'PySide6 not installed')
class GoogleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        from polaris_schedule.view import Bridge
        self.tmp = tempfile.TemporaryDirectory()
        self.schedule = Schedule(self.tmp.name)
        self.schedule.port = SimpleNamespace(id='schedule')
        self.schedule.store.add('Local task', date='2026-11-04')
        self.called = []
        def call(target, operation, params):
            self.called.append((operation, params))
            if operation == 'get':
                return self.schedule.get()
            if operation == 'time_context':
                return self.schedule.time_context()
            if operation == 'add':
                return self.schedule.store.add(**params)
            return {'accepted': True}
        self.messages = []
        self.old_handler = qInstallMessageHandler(lambda kind, context, message: self.messages.append(message))
        self.view = QQuickView()
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.bridge = Bridge(self.schedule, SimpleNamespace(call=call), self.view)
        self.bridge.refresh()
        self.view.engine().rootContext().setContextProperty('scheduleModel', self.bridge)
        import polaris_schedule
        self.view.setSource(QUrl.fromLocalFile(str(Path(polaris_schedule.__file__).with_name('Schedule.qml'))))
        self.assertEqual(self.view.status(), QQuickView.Ready, '\n'.join(e.toString() for e in self.view.errors()))
        self.root = self.view.rootObject()
        self.view.resize(800, 620)
        self.view.show()
        QTest.qWait(30)
        self.root.setProperty('selectedDate', '2026-11-04')

    def tearDown(self):
        self.view.close()
        delete(self.view)
        self.app.processEvents()
        qInstallMessageHandler(self.old_handler)
        self.schedule.google.stop()
        self.tmp.cleanup()
        errors = [m for m in self.messages if any(t in m for t in ('ReferenceError', 'TypeError', 'is not installed', 'Binding loop', 'Unable to assign'))]
        self.assertEqual(errors, [])

    def js(self, expression):
        # Evaluate expressions in the actual QML root object's context.
        from PySide6.QtQml import QQmlExpression, QQmlEngine
        exp = QQmlExpression(QQmlEngine.contextForObject(self.root), self.root, expression)
        value, undefined = exp.evaluate()
        self.assertFalse(exp.hasError(), exp.error().toString())
        return value

    def seed(self):
        service = self.schedule.google
        service.data.update(connected=True, selected=['g'], calendars=[{'id': 'g', 'title': 'Work', 'color': '#4285f4', 'primary': True}],
                            cache={'g': {'events': {
                                'a': {'id': 'a', 'summary': 'All-day trip', 'start': {'date': '2026-11-04'}, 'end': {'date': '2026-11-06'}},
                                'b': {'id': 'b', 'summary': 'UTC meeting', 'start': {'dateTime': '2026-11-04T01:00:00Z'}, 'end': {'dateTime': '2026-11-04T02:00:00Z'}, 'recurringEventId': 'series', 'location': 'Room 1', 'description': '<b>Plain text</b>', 'htmlLink': 'https://www.google.com/calendar/event?eid=test'},
                                'c': {'id': 'c', 'summary': 'Ends at midnight', 'start': {'dateTime': '2026-11-03T23:00:00+08:00'}, 'end': {'dateTime': '2026-11-04T00:00:00+08:00'}}
                            }}}, lastSync='2026-11-04T10:00:00+08:00')
        self.bridge.refresh()
        QTest.qWait(20)

    def test_load_narrow_and_settings(self):
        self.view.resize(320, 360)
        button = self.root.findChild(QObject, 'googleSettings')
        self.assertIsNotNone(button)
        QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection)
        QTest.qWait(30)
        self.assertIsNotNone(self.root.findChild(QObject, 'googleClientPath'))
        self.assertTrue(self.js('googleSettings.visible'))
        self.assertEqual(self.js('googleSettings.google.connected'), False)

    def test_mixed_day_list_and_exclusive_all_day_end(self):
        self.seed()
        self.assertEqual(self.js('googleEvents.length'), 3)
        self.assertEqual(self.js('listEntries.length'), 3)  # Two events, one local task.
        self.assertEqual(self.js("googleEvents.filter(function(e){return e.id==='b'})[0].time"), '09:00')
        self.root.setProperty('selectedDate', '2026-11-05')
        self.assertEqual(self.js('listEntries.length'), 1)
        self.root.setProperty('selectedDate', '2026-11-06')
        self.assertEqual(self.js('listEntries.length'), 0)
        self.root.setProperty('section', '收集箱')
        self.assertEqual(self.js('listEntries.length'), 0)

    def test_week_month_event_and_details(self):
        self.seed()
        self.root.setProperty('presentation', '周')
        QTest.qWait(30)
        planner = self.root.findChild(QObject, 'planner')
        self.assertEqual(planner.property('monthMode'), False)
        self.assertEqual(self.js('googleEvents.length'), 3)
        self.js("openEvent(googleEvents.filter(function(e){return e.id==='b'})[0])")
        QTest.qWait(30)
        self.assertTrue(self.js('googleEvent.visible'))
        self.assertEqual(self.js('googleEvent.event.description'), '<b>Plain text</b>')
        self.assertEqual(self.js('googleEvent.event.timeLabel'), '09:00–10:00')
        self.js('googleEvent.close()')
        self.root.setProperty('presentation', '月')
        QTest.qWait(30)
        self.assertEqual(planner.property('monthMode'), True)

    def test_search_events_and_local_task_add(self):
        self.seed()
        self.root.setProperty('query', 'Room 1')
        self.assertEqual(self.js('listEntries.length'), 1)
        self.root.setProperty('query', '')
        entry = self.root.findChild(QObject, 'quickAdd')
        entry.setProperty('text', 'Still local')
        self.js('addTask()')
        self.assertEqual(self.schedule.store.tasks()[-1]['title'], 'Still local')
        self.assertEqual(len(self.schedule.google.snapshot()['events']), 3)

    def test_operations_and_error_status(self):
        self.seed()
        self.schedule.google.error = 'Network unavailable'
        self.bridge.refresh()
        self.js('googleSettings.open()')
        QTest.qWait(20)
        self.assertEqual(self.js('googleSettings.google.error'), 'Network unavailable')
        self.js("call('google_select', {calendar_ids: []})")
        self.assertIn(('google_select', {'calendar_ids': []}), self.called)


if __name__ == '__main__':
    unittest.main()
