"""Isolated native QML smoke and explicit application controls."""
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
        self.state = dict(feishuInstance='bot-instance', agentInstance='agent-instance',
            feishu=dict(instanceName='项目飞书', connectionState='connected'), agent=dict(model='glm-5.3-flash', ready=True),
            toolGroups=[dict(title='日程', instanceId='schedule-instance', labels=['查看日程','时间信息','查询任务','新增任务','更新任务','删除任务','恢复删除','新增子任务','更新子任务','删除子任务','调整排序','迁移逾期任务','整理当日日程']),
                dict(title='Agent Bridge',instanceId='bridge-instance',labels=['查询会话','查询状态','读取结果','查询投递','标记会话','取消标记','发送任务','查询请求'])],
            tasks=[dict(id='failed', state='failed', chatId='oc_project', threadId='', text='解释这个问题', answer='', error='测试错误'),
                dict(id='done', state='done', chatId='oc_project', threadId='topic', text='一条文字请求', answer='这是 Agent 的回答', error='')])
    @Property(bool, notify=changed)
    def available(self): return True
    @Property(bool, notify=changed)
    def running(self): return self.active
    @Property(str, notify=changed)
    def error(self): return ''
    @Property(bool, notify=changed)
    def stopping(self): return False
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
        self.view.resize(840, 680)
        self.view.show()
        QTest.qWait(20)
    def tearDown(self): self.view.close(); self.view.deleteLater(); self.app.processEvents()
    def click(self, name):
        item = find(self.view.rootObject(), name)
        self.assertIsNotNone(item)
        self.assertTrue(item.property('enabled'))
        self.assertTrue(QMetaObject.invokeMethod(item, 'clicked', Qt.DirectConnection))
        self.app.processEvents()
    def test_explicit_run_retry_and_stop_without_automatic_calls(self):
        self.assertEqual(self.backend.calls, [])
        self.assertIsNotNone(find(self.view.rootObject(), 'feishuAgentTools_日程'))
        self.assertIsNotNone(find(self.view.rootObject(), 'feishuAgentTools_Agent Bridge'))
        self.click('feishuAgentToggle')
        self.assertEqual(self.backend.calls, [('start',)])
        self.click('feishuAgentRetry_failed')
        self.assertEqual(self.backend.calls[-1], ('retry', {'taskId': 'failed'}))
        self.click('feishuAgentToggle')
        self.assertEqual(self.backend.calls[-1], ('stop',))
    def test_narrow_layout_keeps_run_control_visible(self):
        self.view.resize(380, 720)
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
            self.view.resize(840, 680)
            QTest.qWait(20)
            self.view.grabWindow().save(str(directory / 'feishu-agent-wide.png'))

if __name__ == '__main__': unittest.main()
