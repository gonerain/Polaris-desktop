"""Agent presentation owns its view and does not bypass the request context."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components' / 'agent'))

@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt unavailable')
class AgentUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_mount_permission_and_notice_lifecycle(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QUrl, Qt, QObject
        from PySide6.QtQml import QQmlComponent, QQmlEngine
        from polaris_agent.view import Presentation
        engine = QQmlEngine()
        definition = QQmlComponent(engine)
        definition.setData(b'import QtQuick\nItem { width: 410; height: 520 }', QUrl())
        parent = definition.create()
        row = dict(id='key', sessionId='session-1', adapter='Codex', title='A session', marked=True, online=True, canSend=True, runs=[dict(id='run',status='completed',reply='Final reply')])
        class Context:
            denied = False
            calls = []
            def call(self, target, operation, params):
                self.calls.append((operation, params))
                if self.denied:
                    raise ValueError('Permission revoked')
                return {'sessions':[row], 'deliveries':[], 'storageNotice':''} if operation == 'get' else {}
        context = Context()
        component = SimpleNamespace(port=SimpleNamespace(id='org.polaris.agent'))
        presentation = Presentation(component)
        component._presentation = presentation
        result = presentation.create(parent, context, component.port)
        item, _, bridge, _ = presentation._views[result['handle']]
        self.assertEqual(item.objectName(), 'agentView')
        self.assertIn('Final reply', bridge.dataJson)
        item.setProperty('selectedId', 'key')
        self.app.processEvents()
        input_item = item.findChild(QObject, 'agentInput')
        input_item.setProperty('text', 'from input')
        self.app.processEvents()
        item.findChild(QObject, 'agentSend').clicked.emit()
        self.assertIn(('send', {'session_id':'key', 'text':'from input', 'mode':'start'}), context.calls)
        self.assertEqual(input_item.property('text'), '')
        self.assertTrue(bridge.invoke('send', '{"session_id":"key","text":"hello","mode":"start"}'))
        row['runs'].append(dict(id='new-run', status='running', reply=None))
        bridge.refresh()
        item.setProperty('chosenRunId', 'run')
        self.app.processEvents()
        self.assertEqual(item.findChild(QObject, 'agentSendMode').property('currentIndex'), 1)
        input_item.setProperty('text', 'another message')
        row['marked'] = False
        bridge.refresh()
        self.app.processEvents()
        self.assertFalse(item.findChild(QObject, 'agentSend').property('enabled'))
        context.denied = True
        self.assertFalse(bridge.invoke('send', '{"session_id":"key","text":"again"}'))
        self.assertFalse(bridge.refresh())
        self.assertEqual(bridge.dataJson, '{}')
        self.assertIn('Permission revoked', bridge.lastError)
        import threading
        worker = threading.Thread(target=lambda: presentation.show_notice(row, {'status':'unknown'}))
        worker.start()
        worker.join()
        self.app.processEvents()
        self.assertIsNotNone(presentation._notice)
        self.assertFalse(presentation._notice.isActive())
        self.assertTrue(presentation._notice.flags() & Qt.WindowDoesNotAcceptFocus)
        self.assertEqual(presentation._notice.rootObject().property('noticeState'), '结束未确认')
        self.assertTrue(presentation.release(result['handle'])['released'])
        self.assertFalse(presentation.closed)
        presentation.close()
        presentation.show_notice(row, {'status':'completed'})
        self.app.processEvents()
        self.assertTrue(presentation.closed)
        self.assertIsNone(presentation._notice)
        parent.deleteLater()
        self.app.processEvents()

    def test_autostart_before_application_notifies_without_view(self):
        import subprocess
        script = r'''
import tempfile,time
from types import SimpleNamespace
from polaris_agent import Agent
with tempfile.TemporaryDirectory() as directory:
    component = Agent(directory)
    component.start(SimpleNamespace(id='org.polaris.agent'))
    row = component.store.snapshot('fake','client','session',title='Before GUI')
    component.mark(row['id'])
    component.store.run_event(row['id'],'run','completed','reply')
    assert component._presentation is None
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])
    deadline = time.monotonic()+4
    while time.monotonic()<deadline:
        app.processEvents()
        presentation = component._presentation
        if presentation and presentation._notice:
            break
        time.sleep(.01)
    assert presentation is not None
    assert presentation._notice is not None
    assert presentation._notice.isVisible()
    assert not presentation._notice.isActive()
    assert not presentation._views
    component.stop()
    app.processEvents()
'''
        environment = dict(os.environ)
        environment['PYTHONPATH'] = os.pathsep.join((str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'components' / 'agent')))
        completed = subprocess.run([sys.executable, '-c', script], env=environment, capture_output=True, text=True, timeout=12)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
