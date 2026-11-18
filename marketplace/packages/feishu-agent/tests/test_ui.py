"""Native QML: minimal default view, explicit actions and folded diagnostics."""
import json
import os
from pathlib import Path
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QMetaObject, Qt, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest


class Backend(QObject):
    changed = Signal()
    completed = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.active = False
        self.state = dict(connected=True, session='/work/project', sessionId='hidden-session-id', pending=0,
                          issues=[], attention=[], callback=dict(target='app-id', operation='bridge_output', params={}))

    @Property(bool, notify=changed)
    def available(self): return True
    @Property(bool, notify=changed)
    def running(self): return self.active
    @Property(str, notify=changed)
    def error(self): return ''
    @Property(bool, notify=changed)
    def stopping(self): return False
    @Property(str, notify=changed)
    def warningsJson(self): return json.dumps(['请连接 codexSend'], ensure_ascii=False)
    @Property(str, notify=changed)
    def stateJson(self): return json.dumps(self.state, ensure_ascii=False)
    @Slot()
    def start(self): self.calls.append(('start',)); self.active = True; self.changed.emit()
    @Slot()
    def stop(self): self.calls.append(('stop',)); self.active = False; self.changed.emit()
    @Slot(str, 'QVariantMap', str)
    def call(self, command, params, request): self.calls.append((command, params)); self.completed.emit(request, '{}')


def find(item, name):
    if item.objectName() == name: return item
    for child in item.childItems():
        result = find(child, name)
        if result is not None: return result


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.backend = Backend()
        self.view = QQuickView()
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.view.rootContext().setContextProperty('appBackend', self.backend)
        self.view.setSource(QUrl.fromLocalFile(str(Path(__file__).parents[1] / 'Main.qml')))
        self.assertFalse(self.view.errors(), [e.toString() for e in self.view.errors()])
        self.view.resize(640, 520)
        self.view.show()
        QTest.qWait(20)
    def tearDown(self): self.view.close(); self.view.deleteLater(); self.app.processEvents()
    def click(self, name):
        item = find(self.view.rootObject(), name)
        self.assertIsNotNone(item)
        self.assertTrue(item.property('enabled'))
        self.assertTrue(QMetaObject.invokeMethod(item, 'clicked', Qt.DirectConnection))
        self.app.processEvents()
    def test_default_view_hides_callback_address_and_capability_dump(self):
        self.assertEqual(self.backend.calls, [])
        self.assertFalse(find(self.view.rootObject(), 'feishuAgentCallback').property('visible'))
        self.assertFalse(find(self.view.rootObject(), 'feishuAgentWarnings').property('visible'))
        self.click('feishuAgentSettings')
        self.assertTrue(find(self.view.rootObject(), 'feishuAgentCallback').property('visible'))
        self.assertTrue(find(self.view.rootObject(), 'feishuAgentWarnings').property('visible'))
    def test_run_and_stop_are_explicit(self):
        self.click('feishuAgentToggle')
        self.assertEqual(self.backend.calls, [('start',)])
        self.click('feishuAgentToggle')
        self.assertEqual(self.backend.calls[-1], ('stop',))
    def test_card_buttons_are_explicit_and_require_running_connected_chat(self):
        self.assertFalse(find(self.view.rootObject(), 'feishuAgentSessionsCard').property('enabled'))
        self.click('feishuAgentToggle')
        self.click('feishuAgentSessionsCard')
        self.click('feishuAgentScheduleCard')
        self.assertEqual(self.backend.calls[-2:], [('show_sessions', {}), ('show_schedule', {})])
        self.backend.state['connected'] = False
        self.backend.changed.emit()
        self.app.processEvents()
        self.assertFalse(find(self.view.rootObject(), 'feishuAgentSessionsCard').property('enabled'))
        self.assertFalse(find(self.view.rootObject(), 'feishuAgentScheduleCard').property('enabled'))
    def test_only_attention_items_are_listed_and_retries_are_explicit(self):
        self.backend.state['attention'] = [dict(id='failed', kind='inputs', state='failed', text='new input', error='denied')]
        self.backend.changed.emit()
        QTest.qWait(10)
        self.click('feishuAgentRetry_failed')
        self.assertEqual(self.backend.calls, [('retry', {'kind': 'inputs', 'id': 'failed'})])
    def test_narrow_layout_keeps_run_control_visible(self):
        self.view.resize(380, 600)
        self.app.processEvents()
        button = find(self.view.rootObject(), 'feishuAgentToggle')
        end = button.mapToScene(QPointF(button.width(), button.height()))
        self.assertLessEqual(end.x(), self.view.width())
        self.assertLessEqual(end.y(), self.view.height())
        capture = os.environ.get('POLARIS_FEISHU_AGENT_CAPTURE')
        if capture:
            directory = Path(capture)
            directory.mkdir(parents=True, exist_ok=True)
            self.view.grabWindow().save(str(directory / 'feishu-agent-narrow.png'))
            self.view.resize(640, 520)
            QTest.qWait(20)
            self.view.grabWindow().save(str(directory / 'feishu-agent-wide.png'))


if __name__ == '__main__': unittest.main()
