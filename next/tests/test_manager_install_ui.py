"""Manager installation confirmations through real Qt controls in an isolated process."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ManagerInstallationUIProcessTests(unittest.TestCase):
    def test_installation_controls(self):
        import importlib.util
        if importlib.util.find_spec('PySide6') is None:
            self.skipTest('Optional PySide6 is not installed')
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'child'],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
            capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def exercise():
    import copy
    import json
    import tempfile
    import time
    from PySide6.QtCore import QObject, QPoint, Qt, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest
    from polaris_platform.desktop.manager import ManagerBridge

    class Runtime:
        roles = {}
        def __init__(self):
            self.calls = []
            self.record = dict(manifest=dict(id='example', name='示例'), installationId='identity', directory='/old')
            self.authorization = type('Authorization', (), {'decisions': lambda self: []})()
        def snapshot(self):
            return [dict(id='example', installation=self.record['installationId'], instance=None,
                         state='installed', manifest=self.record['manifest'], description={})] if self.record else []
        def export_installations(self): return [copy.deepcopy(self.record)] if self.record else []
        def install_directory(self, path, replace=False): self.calls.append(('install', path, replace))
        def uninstall_component(self, target):
            self.calls.append(('uninstall', target))
            self.record = None

    app = QGuiApplication([])
    runtime = Runtime()
    bridge = ManagerBridge(runtime)
    window = QQuickView()
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.rootContext().setContextProperty('manager', bridge)
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).parents[1] / 'polaris_platform/desktop/Manager.qml')))
    assert not window.errors(), window.errors()
    window.resize(1040, 760)
    window.show()
    QTest.qWait(150)
    def wait():
        deadline = time.monotonic() + 3
        while bridge.busy and time.monotonic() < deadline: QTest.qWait(10)
        QTest.qWait(40)
        assert not bridge.busy
    def click(name):
        def find(item):
            if item.objectName() == name: return item
            for child in item.childItems():
                found = find(child)
                if found is not None: return found
        control = window.rootObject().findChild(QObject, name)
        if control is None: control = find(window.contentItem())
        assert control is not None, name
        point = control.mapToScene(control.boundingRect().center())
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
        wait()
    bridge.refresh(); wait()
    click('uninstallComponent')
    assert bridge._installation_plan['target'] == 'example'
    click('cancelInstallation')
    assert runtime.calls == [] and bridge._installation_plan is None
    with tempfile.TemporaryDirectory() as directory:
        manifest = dict(id='example', name='示例', version='2')
        (Path(directory) / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        bridge.submit(lambda: time.sleep(0.08))
        bridge.loadDirectory(directory); wait()
        assert bridge._installation_plan is not None
        assert runtime.calls == []
        click('cancelInstallation')
        bridge.loadDirectory(directory); wait()
        click('confirmInstallation')
        assert runtime.calls == [('install', directory, True)], runtime.calls
        bridge.loadDirectory(directory); wait()
        runtime.record['installationId'] = 'changed'
        click('confirmInstallation')
        assert len(runtime.calls) == 1 and '已变化' in bridge.notice
        bridge.loadDirectory(directory); wait()
        manifest['version'] = '3'
        (Path(directory) / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        click('confirmInstallation')
        assert len(runtime.calls) == 1 and '目录已变化' in bridge.notice
    click('uninstallComponent')
    click('confirmInstallation')
    assert runtime.calls[-1] == ('uninstall', 'example')
    assert bridge.notice == '已卸载“示例”'
    # Source discovery and installation are separate, explicit Qt actions.
    import threading
    release = threading.Event()
    class Sources:
        def __init__(self): self.rows = []; self.installs = []
        def local_source_control(self): return self
        def sources(self): return self.rows
        def add(self, location):
            release.wait(2)
            self.rows = [dict(id='source', revision='commit', location=location, name='测试源', components=[
                dict(path='one', manifest=dict(id='one', name='插件一', version='1')),
                dict(path='two', manifest=dict(id='two', name='插件二', version='1'))])]
        def install(self, source, target, **kwargs):
            from PySide6.QtCore import QThread
            assert QThread.currentThread() == app.thread(), 'Plugin lifecycle must use the GUI thread'
            self.installs.append((source, target, kwargs))
    sources = Sources()
    source_state = {'state': 'running'}
    runtime.status = lambda target: source_state
    runtime.component_instance = lambda target: sources
    click('sourceButton')
    location = window.rootObject().findChild(QObject, 'sourceLocation')
    location.setProperty('text', '/tmp/example-source')
    control = window.rootObject().findChild(QObject, 'addSource')
    point = control.mapToScene(control.boundingRect().center())
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
    QTest.qWait(30)
    assert bridge.busy and not control.property('enabled')
    assert sources.installs == []
    release.set(); wait()
    assert len(json.loads(bridge.sourcesJson)[0]['components']) == 2
    assert sources.installs == []
    click('installSource_one')
    assert sources.installs == [('source', 'one', {})]
    # Same ID source replacement uses the existing confirmation and identity check.
    runtime.record = dict(manifest=dict(id='one', name='插件一'), installationId='old', directory='/old')
    click('installSource_one')
    assert len(sources.installs) == 1
    click('cancelInstallation')
    click('installSource_one')
    runtime.record['installationId'] = 'changed'
    click('confirmInstallation')
    assert len(sources.installs) == 1 and '已变化' in bridge.notice
    click('installSource_one')
    click('confirmInstallation')
    assert sources.installs[-1] == ('source', 'one', dict(replace=True, expected_installation='changed', expected_revision='commit'))
    source_state['state'] = 'stopped'
    bridge.addSource('/tmp/stopped-source'); wait()
    assert bridge.notice == '插件源管理未运行'
    assert len(sources.rows) == 1 and len(sources.installs) == 2
    bridge._closed = True
    window.close()


if __name__ == '__main__':
    if 'child' in sys.argv: exercise()
    else: unittest.main()
