import json
from pathlib import Path
import tempfile
import unittest

try:
    from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QTimer, QEventLoop, Qt, QEvent, QPointF, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QMouseEvent
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQml import QQmlExpression, QQmlEngine
    from shiboken6 import delete
except ImportError:
    QGuiApplication = None

from polaris_schedule import Schedule

PACKAGE = Path(__file__).resolve().parents[1]


def wait(ms=20):
    loop=QEventLoop(); QTimer.singleShot(ms,loop.quit); loop.exec()


if QGuiApplication:
    class Bridge(QObject):
        changed=Signal()
        completed=Signal(str,str)
        failed=Signal(str,str)
        def __init__(self,schedule):
            super().__init__(); self.schedule=schedule; self.enabled=True; self.calls=[]; self.fail_write=False
        @Property(bool,notify=changed)
        def active(self): return self.enabled
        @Slot(str,'QVariantMap',str)
        def call(self,alias,params,request):
            self.calls.append((alias,dict(params)))
            def finish():
                try:
                    if alias=='get': value=self.schedule.get()
                    elif self.fail_write: raise ValueError('保存失败，请保留输入')
                    elif alias.startswith('google_'): value={'accepted':True}
                    else: value=getattr(self.schedule.store,alias)(**params)
                    self.completed.emit(request,json.dumps(value,ensure_ascii=False))
                except Exception as error: self.failed.emit(request,str(error))
            QTimer.singleShot(0,self,finish)


@unittest.skipIf(QGuiApplication is None,'PySide6 required')
class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.schedule=Schedule(self.tmp.name)
        self.schedule.store.add('Inbox task')
        self.schedule.store.add('Timed task',date='2026-11-17',time='10:00',notes='Notes')
        self.schedule.google.data.update(connected=True,selected=['g'],calendars=[{'id':'g','title':'Work','color':'#5298e9','primary':True}],cache={'g':{'events':{
            'e':{'id':'e','summary':'Design review','start':{'dateTime':'2026-11-17T09:00:00+08:00'},'end':{'dateTime':'2026-11-17T10:30:00+08:00'},'htmlLink':'https://www.google.com/calendar/event?eid=test'},
            'e2':{'id':'e2','summary':'Overlapping meeting','start':{'dateTime':'2026-11-17T09:30:00+08:00'},'end':{'dateTime':'2026-11-17T11:00:00+08:00'}},
            'a':{'id':'a','summary':'All-day trip','start':{'date':'2026-11-17'},'end':{'date':'2026-11-19'}}
        }}},lastSync='2026-11-17T10:00:00+08:00')
        self.messages=[];self.old=qInstallMessageHandler(lambda kind,ctx,message:self.messages.append(message))
        self.bridge=Bridge(self.schedule);self.view=QQuickView();self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.view.engine().rootContext().setContextProperty('appCapabilities',self.bridge)
        self.view.setSource(QUrl.fromLocalFile(str(PACKAGE/'Main.qml')))
        self.assertEqual(self.view.status(),QQuickView.Ready,'\n'.join(self.messages))
        self.root=self.view.rootObject();self.view.resize(1280,800);self.view.show();wait()
        self.root.setProperty('selectedDate','2026-11-17')
    def tearDown(self):
        self.view.close();delete(self.view);delete(self.bridge);self.app.processEvents();qInstallMessageHandler(self.old)
        self.schedule.google.stop();self.tmp.cleanup()
        errors=[m for m in self.messages if any(k in m for k in ('ReferenceError','TypeError','Unable to assign','Binding loop','not a type','Cannot assign','is not defined'))]
        self.assertEqual(errors,[])
    def js(self,code):
        exp=QQmlExpression(QQmlEngine.contextForObject(self.root),self.root,code);value,_=exp.evaluate()
        self.assertFalse(exp.hasError(),exp.error().toString());return value
    def test_views_resize_and_render(self):
        self.assertTrue(self.root.property('ready'))
        for mode in ['周','日','月','计划']:
            self.root.setProperty('viewMode',mode);wait()
        self.view.resize(640,600);self.root.setProperty('viewMode','周');wait()
        self.view.resize(1280,800);self.root.setProperty('viewMode','周');wait()
        self.view.grabWindow().save('/tmp/polaris-schedule-app.png')
    def test_create_edit_delete_and_undo(self):
        self.js("newTask('2026-11-17','13:30')");self.js("changeDraft('title','New task')");self.js('saveDetail()');wait()
        task=next(t for t in self.schedule.store.tasks() if t['title']=='New task');self.assertEqual(task['time'],'13:30')
        self.js("openTask(snapshot.tasks.filter(function(t){return t.id==='"+task['id']+"'})[0])");self.js("changeDraft('notes','Edited')");self.js('saveDetail()');wait()
        self.assertEqual(self.schedule.store.get(task['id'])['notes'],'Edited')
        self.js("write('delete',{identity:'"+task['id']+"'},true)");wait();self.assertTrue(self.schedule.store.can_undo)
        self.js("write('undo_delete',{})");wait();self.assertEqual(self.schedule.store.get(task['id'])['notes'],'Edited')
    def test_unsaved_draft_and_failed_write(self):
        self.js("newTask(null,'')");self.js("changeDraft('title','Keep my input')");self.bridge.fail_write=True
        self.js('saveDetail()');wait();self.assertEqual(self.js('draft.title'),'Keep my input');self.assertTrue(self.js('dirty'));self.assertFalse(self.js('saving'))
        self.js('closeDetail()');self.assertIsNotNone(self.js('detail'));self.assertTrue(self.js('discard.visible'))
    def test_schedule_task_and_subtasks(self):
        task=self.schedule.store.tasks()[0]
        self.js("schedule(snapshot.tasks[0],'2026-11-18','08:30')");wait()
        self.assertEqual(self.schedule.store.get(task['id'])['time'],'08:30')
        self.js("write('add_subtask',{identity:'"+task['id']+"',title:'Step'})");wait()
        self.assertEqual(self.schedule.store.get(task['id'])['subtasks'][0]['title'],'Step')
    def test_calendar_visibility_search_and_details(self):
        self.assertEqual(self.js('events.length'),3)
        self.js("toggleCalendar('g')");self.assertEqual(self.js('events.length'),0)
        self.js("toggleCalendar('g')");self.root.setProperty('query','Design');self.assertEqual(self.js('events.length'),1)
        self.js('openItem(events[0])');self.assertTrue(self.js('detail.googleEvent'))
        self.assertIn('09:00',self.js('detail.detailTime'))
    def test_calendar_math_overlap_and_exclusive_end(self):
        self.assertEqual(self.js("Cal.shift('2024-02-28',1)"),'2024-02-29')
        self.assertEqual(self.js("Cal.changeMonth('2024-01-31',1)"),'2024-02-29')
        self.assertEqual(self.js("Cal.timed(events,[],'2026-11-17')[0].columns"),2)
        self.assertFalse(self.js("Cal.onDay(events.filter(function(e){return e.id==='a'})[0],'2026-11-19')"))
    def test_inactive_view_clears_snapshot(self):
        self.bridge.enabled=False;self.bridge.changed.emit();wait()
        self.assertEqual(self.js('(snapshot.tasks||[]).length'),0)
        self.assertFalse(self.root.property('ready'))
    def test_google_settings_and_narrow_inspector(self):
        self.js('google.open()');wait();self.js('google.close()')
        self.view.resize(640,600);wait();self.js('openItem(events[0])');wait()
        self.assertTrue(self.js('detailPopup.visible'))
    def test_single_header_at_medium_and_narrow_sizes(self):
        def visual(item,name):
            if item.objectName()==name:return item
            for child in item.childItems():
                found=visual(child,name)
                if found is not None:return found
        self.view.resize(1144,700);wait()
        header=self.root.findChild(QObject,'scheduleAppHeader')
        done=self.root.findChild(QObject,'showCompleted')
        week=visual(self.root,'view_周')
        self.assertLess(done.mapToScene(QPointF()).y(),header.height())
        self.assertLess(week.mapToScene(QPointF()).y(),header.height())
        self.assertEqual(header.height(),62)
        self.assertLessEqual(done.mapToScene(QPointF(done.width(),0)).x(),self.view.width())
        self.view.resize(640,600);wait()
        compact=self.root.findChild(QObject,'scheduleAppCompactView')
        self.assertTrue(compact.isVisible());self.assertTrue(done.isVisible())
        self.assertLessEqual(done.mapToScene(QPointF(done.width(),0)).x(),self.view.width())
        self.view.grabWindow().save('/tmp/polaris-schedule-app-compact.png')
    def test_drag_inbox_to_time_grid(self):
        task=next(t for t in self.schedule.store.tasks() if not t['date'])
        self.js('sidebarScroll.contentItem.contentY=Math.max(0,sidebarScroll.contentItem.contentHeight-sidebarScroll.height)');wait()
        def visual(item,name):
            if item.objectName()==name:return item
            for child in item.childItems():
                found=visual(child,name)
                if found is not None:return found
        grip=visual(self.root,'taskGrip_'+task['id']);target=visual(self.root,'timeDay_2026-11-18')
        start=grip.mapToScene(QPointF(grip.width()/2,grip.height()/2));end=target.mapToScene(QPointF(target.width()/2,9*64+32))
        def send(kind,point,button,buttons):QGuiApplication.sendEvent(self.view,QMouseEvent(kind,point,point,button,buttons,Qt.NoModifier))
        send(QEvent.MouseButtonPress,start,Qt.LeftButton,Qt.LeftButton)
        for step in range(1,21):
            p=start+(end-start)*(step/20);send(QEvent.MouseMove,p,Qt.NoButton,Qt.LeftButton);wait(2)
        send(QEvent.MouseButtonRelease,end,Qt.LeftButton,Qt.NoButton);wait()
        updated=self.schedule.store.get(task['id']);self.assertEqual(updated['date'],'2026-11-18');self.assertEqual(updated['time'],'09:30')
    def test_header_creation_and_contracts(self):
        button=self.root.findChild(QObject,'createTask');point=button.mapToScene(QPointF(button.width()/2,button.height()/2))
        for kind,buttons in [(QEvent.MouseButtonPress,Qt.LeftButton),(QEvent.MouseButtonRelease,Qt.NoButton)]:
            QGuiApplication.sendEvent(self.view,QMouseEvent(kind,point,point,Qt.LeftButton,buttons,Qt.NoModifier))
        wait();self.assertIsNotNone(self.js('detail'))
        self.js("changeDraft('title','Header task')");self.js('saveDetail()');wait()
        self.assertTrue(any(t['title']=='Header task' for t in self.schedule.store.tasks()))
        self.assertIsNone(self.root.findChild(QObject,'scheduleAppQuickAdd'))
        required=json.loads((PACKAGE/'polaris-application.json').read_text())['requires'];ops=self.schedule.describe()['operations']
        for alias,req in required.items():
            self.assertEqual(ops[alias]['applicationBinding'],'instance')
            self.assertIn(req['contract'],ops[alias]['provides'])

if __name__=='__main__':unittest.main()
