"""Trusted extension management shares the Canvas and preserves public authority."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

if __name__ != '__main__':
    class EmbeddedManagementProcessTests(unittest.TestCase):
        def test_trusted_management_and_settings(self):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import json
    import tempfile
    import time
    from PySide6.QtCore import QObject, QMetaObject, Qt, QCoreApplication, QEvent
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.desktop import Canvas, WindowHost, Manager, Pet
    from polaris_platform.protocol import PlatformError

    def find(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            result = find(child, name)
            if result is not None:
                return result
        return None

    class EmbeddedManagementTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.runtime = build(default_config(), state_dir=Path(self.temp.name) / 'runtime')
            self.windowHost = WindowHost(runtime=self.runtime)
            self.canvas = Canvas(runtime=self.runtime, data_dir=self.temp.name, collapse_delay=100000)
            self.manager = Manager(self.runtime)
            self.pet = Pet(runtime=self.runtime)
            for identity, component in [('window', self.windowHost), ('canvas', self.canvas),
                                        ('manager', self.manager), ('pet', self.pet), ('user', Component())]:
                self.runtime.install(dict(id=identity, name=identity, version='1', platformApi=1,
                                          entry={'mode': 'inprocess'}), lambda c=component: c)
                self.runtime.start_component(identity)

        def tearDown(self):
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'], force=True, persist=False)
            for _ in range(5):
                self.app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.temp.cleanup()

        def wait(self, predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(5)
            self.assertTrue(predicate(), self.manager.bridge.notice)

        def open_management(self):
            self.manager.show()
            self.wait(lambda: self.manager.status()['visible'])
            self.window = self.windowHost._views[self.canvas.handle]
            self.root = self.window.rootObject()
            self.page = find(self.root, 'extensionManagementPage')

        def click(self, name):
            item = find(self.window.contentItem(), name)
            self.assertIsNotNone(item, name)
            self.assertTrue(item.isVisible(), name)
            self.assertTrue(item.isEnabled(), name)
            self.assertTrue(QMetaObject.invokeMethod(item, 'clicked', Qt.DirectConnection))
            QTest.qWait(20)
            return item

        def test_public_window_permissions_stay_required_and_real_pet_path_opens_embedded_management(self):
            self.runtime.grant('user', 'canvas', 'show')
            with self.assertRaises(PlatformError) as failure:
                self.runtime.client('user').call('canvas', 'show', context=self.runtime.user_context('user'))
            self.assertEqual(failure.exception.code, 'permission_required')
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.runtime.grant('pet', 'manager', 'show')
            self.pet.bridge.management()
            self.wait(lambda: self.manager.status()['visible'])
            self.assertFalse(self.pet.bridge.notice)
            self.assertFalse(self.runtime.authorization.scope('canvas'), 'Local presentation creates no grants')
            self.runtime.validate_context(self.canvas.session_context)
            self.assertEqual(self.canvas.session_context.caller, 'canvas')
            self.assertEqual(self.windowHost._owners[self.canvas.handle], 'canvas')
            self.assertFalse(hasattr(self.manager, '_view'), 'There is no independent management window')
            # A public Manager handler running on the GUI thread must queue a new
            # GUI event before user_context is created, rather than clearing _active.
            self.canvas.hide(self.canvas.session_context)
            self.runtime.grant('user', 'manager', 'show')
            self.runtime.client('user').call('manager', 'show', context=self.runtime.user_context('user'))
            self.wait(lambda: self.manager.status()['visible'])
            with self.assertRaises(PlatformError):
                self.runtime.client('user').call('canvas', 'show', context=self.runtime.user_context('user'))

        def test_disabled_canvas_can_be_explicitly_recovered_by_management(self):
            self.open_management()
            previous = self.canvas.actions._window
            self.assertIsNotNone(previous)
            self.runtime.stop_component('canvas')
            self.assertIsNone(self.canvas.actions._window)
            self.runtime.stop_component('manager')
            self.runtime.start_component('manager')
            self.assertEqual(self.runtime.status('canvas')['state'], 'stopped')
            self.assertFalse(self.manager.status()['visible'])
            self.open_management()
            self.assertEqual(self.runtime.status('canvas')['state'], 'running')
            self.assertTrue(self.manager.status()['embedded'])

        def test_stopping_canvas_ends_its_installation_confirmation(self):
            self.open_management()
            self.manager.bridge.prepareUninstall('user')
            self.wait(lambda: self.manager.bridge._installation_plan is not None and not self.manager.bridge.busy)
            self.runtime.stop_component('canvas')
            self.app.processEvents()
            self.assertIsNone(self.manager.bridge._installation_plan)
            self.assertIn('user', [row['id'] for row in self.runtime.snapshot()])

        def test_settings_hierarchy_and_application_management_selection_are_independent(self):
            self.open_management()
            host = self.canvas.application_host
            before = host._selected
            package = Path(self.temp.name) / 'source'
            package.mkdir()
            (package / 'Main.qml').write_text('import QtQuick\nItem { objectName: "managedFixtureApp" }')
            manifest = dict(id='fixture.managed', name='管理测试应用', version='1',
                            entry={'adapter': 'qt-quick', 'file': 'Main.qml'}, requires={})
            (package / 'polaris-application.json').write_text(json.dumps(manifest))
            identity = host.installPackage(str(package))
            self.assertTrue(identity, host.error)
            self.assertEqual(host._selected, before)
            self.click('managedApplication_' + identity)
            self.assertEqual(host._selected, before)
            self.assertNotIn(identity, host._views)
            self.assertTrue(self.root.property('settingsOpen'))
            self.assertEqual(self.root.property('settingsSection'), 'extensions')
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            for width in (1300, 720, 620, 619, 360):
                self.window.resize(width, 760)
                QTest.qWait(25)
                self.assertGreater(self.page.width(), 0)
                if capture:
                    Path(capture).mkdir(parents=True, exist_ok=True)
                    self.window.grabWindow().save(str(Path(capture) / f'extensions-applications-{width}.png'))
            self.click('openManagedApplication')
            self.wait(lambda: identity in host._views)
            self.assertEqual(host._selected, identity)
            self.assertFalse(self.root.property('settingsOpen'))
            view = host._views[identity]
            self.assertIsNone(view.context.contextProperty('manager'))
            self.assertIsNone(view.context.contextProperty('canvasActions'))
            self.assertIsNone(view.context.contextProperty('applicationHost'))
            self.assertIsNone(view.context.contextProperty('managementBridge'))

        def test_dense_lists_keep_detail_actions_visible_at_each_width(self):
            for index in range(12):
                identity = 'fixture.component.' + str(index)
                component = Component()
                self.runtime.install(dict(id=identity, name='测试组件 ' + str(index + 1), version='1',
                    platformApi=1, entry={'mode':'inprocess'}), lambda c=component: c)
            self.open_management()
            self.manager.bridge.refresh()
            self.wait(lambda: not self.manager.bridge._busy)
            host = self.canvas.application_host
            for index in range(12):
                package = Path(self.temp.name) / ('app' + str(index))
                package.mkdir()
                (package / 'Main.qml').write_text('import QtQuick\nItem {}')
                (package / 'polaris-application.json').write_text(json.dumps(dict(
                    id='fixture.application.' + str(index), name='测试应用 ' + str(index + 1), version='1',
                    entry={'adapter':'qt-quick','file':'Main.qml'}, requires={})))
                self.assertTrue(host.installPackage(str(package)), host.error)
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            for category, action in [('components','startComponentInstance'), ('applications','openManagedApplication')]:
                self.page.setProperty('category', category)
                if category == 'components': self.page.setProperty('selectedId', 'fixture.component.11')
                for width in (1300,720,360):
                    self.window.resize(width,760)
                    QTest.qWait(40)
                    control = find(self.window.contentItem(), action)
                    point = control.mapToScene(control.boundingRect().center())
                    self.assertTrue(control.isVisible())
                    self.assertLess(point.y(), 720, (width,category,point.y()))
                    self.assertGreater(point.y(), 0)
                    self.assertGreaterEqual(point.x(), 0)
                    self.assertLess(point.x(), width)
                    selector = find(self.window.contentItem(), category + 'CompactSelector')
                    self.assertEqual(selector.isVisible(), not self.page.property('wideDetails'))
                    if selector.isVisible():
                        selector.forceActiveFocus()
                        QTest.keyClick(self.window, Qt.Key_End)
                        QTest.keyClick(self.window, Qt.Key_Return)
                        QTest.qWait(10)
                        self.assertTrue(selector.hasActiveFocus())
                    if capture:
                        Path(capture).mkdir(parents=True,exist_ok=True)
                        self.window.grabWindow().save(str(Path(capture) / ('dense-' + category + '-' + str(width) + '.png')))

        def test_bundled_real_catalog_search_and_responsive_layout(self):
            from polaris_platform.sources import Sources
            sources = Sources(self.runtime, Path(self.temp.name) / 'source-state')
            self.runtime.install(dict(id='sources',name='Sources',version='1',platformApi=1,entry={'mode':'inprocess'}), lambda:sources)
            self.runtime.start_component('sources')
            control = sources.local_source_control()
            import shutil
            legacy = Path(self.temp.name) / 'legacy-source'
            legacy.mkdir()
            shutil.copytree(ROOT.parent / 'marketplace/packages/text-tools', legacy / 'component')
            (legacy / 'polaris-source.json').write_text(json.dumps(dict(schemaVersion=1, name='旧源',
                components=[{'path':'component'}])))
            old_source = control.add(str(legacy))
            old_install = control.install(old_source['id'], 'org.example.text-tools')
            source = control.add(str(ROOT.parent / 'marketplace'))
            self.open_management()
            self.manager.bridge.refresh(); self.wait(lambda: not self.manager.bridge._busy)
            rows = json.loads(self.manager.bridge.sourcesJson)
            for row in rows:
                row['defaultCatalog'] = row['id'] == source['id']
            self.manager.bridge._sources_json = json.dumps(rows, ensure_ascii=False)
            self.manager.bridge.sourcesChanged.emit()
            from unittest.mock import patch
            with patch.object(sources, 'sources', wraps=sources.sources) as opened_catalog:
                self.page.setProperty('category','market')
                self.wait(lambda: opened_catalog.call_count > 0 and not self.manager.bridge._busy and not self.manager.bridge._pending_refresh)
            QTest.qWait(40)
            self.assertEqual(self.page.property('marketSource'), source['id'])
            def entries():
                value = self.page.property('marketEntries')
                return value.toVariant() if hasattr(value, 'toVariant') else value
            self.assertEqual({entry['manifest']['id'] for entry in entries()}, {
                'org.polaris.schedule', 'org.polaris.schedule-app', 'org.polaris.weixin',
                'org.polaris.agent', 'assistant', 'org.polaris.feishu-bot',
                'org.polaris.feishu-agent', 'org.example.text-tools',
                'org.example.text-studio', 'org.polaris.codex-cli',
            })
            self.assertTrue(all(entry.get('iconUrl', '').startswith('file:') for entry in entries()))
            self.assertEqual(find(self.window.contentItem(), 'installSource_org.example.text-tools').property('text'), '已安装')
            self.assertTrue(find(self.window.contentItem(), 'changeSource_org.example.text-tools').isVisible())
            self.assertEqual(control.installation_origin('org.example.text-tools')['sourceId'], old_source['id'])
            self.assertEqual(self.runtime.status('org.example.text-tools')['installation'], old_install['installationId'])
            self.manager.bridge.refresh(); self.wait(lambda: not self.manager.bridge._busy and not self.manager.bridge._pending_refresh)
            # Real timer refreshes must not recreate unchanged market delegates.
            import shiboken6
            change_button = find(self.window.contentItem(), 'changeSource_org.example.text-tools')
            self.assertTrue(change_button.isEnabled())
            source_notifications, completed_polls, enabled_states = [], [], []
            self.manager.bridge.sourcesChanged.connect(lambda: source_notifications.append(True))
            self.manager.bridge.completed.connect(lambda result: completed_polls.append(True))
            self.manager.bridge.changed.connect(lambda: enabled_states.append(shiboken6.isValid(change_button) and change_button.isEnabled()))
            with patch.object(sources, 'sources', wraps=sources.sources) as sampled, patch.object(sources, '_installation_origin', wraps=sources._installation_origin) as digests:
                self.wait(lambda: len(completed_polls) >= 2)
                self.assertEqual(sampled.call_count, 0, 'Timer sampled the source catalog')
                self.assertEqual(digests.call_count, 0, 'Timer recalculated source origins')
            self.assertEqual(source_notifications, [], 'Unchanged catalog emitted a data notification')
            self.assertTrue(all(enabled_states), 'Background refresh disabled the market button')
            self.assertTrue(shiboken6.isValid(change_button), 'Periodic refresh recreated the market button')
            self.assertIs(change_button, find(self.window.contentItem(), 'changeSource_org.example.text-tools'))
            self.assertTrue(change_button.isEnabled())
            # A user action during a blocked background snapshot remains available and executes once.
            import threading
            entered, release = threading.Event(), threading.Event()
            snapshot = self.runtime.snapshot
            def blocked_snapshot():
                entered.set()
                release.wait()
                return snapshot()
            start = self.runtime.start_component
            try:
                with patch.object(self.runtime, 'snapshot', side_effect=blocked_snapshot), patch.object(self.runtime, 'start_component', wraps=start) as started, patch.object(self.manager.bridge, '_installation_confirmation', wraps=self.manager.bridge._installation_confirmation) as confirmed:
                    self.manager.bridge.poll()
                    self.wait(entered.is_set)
                    self.assertFalse(self.manager.bridge.busy)
                    self.assertTrue(change_button.isEnabled())
                    self.click('changeSource_org.example.text-tools')
                    self.manager.bridge.lifecycle('org.example.text-tools', 'start')
                    release.set()
                    self.wait(lambda: self.manager.bridge._installation_plan is not None)
                    self.manager.bridge.cancelInstallation()
                    self.wait(lambda: self.runtime.status('org.example.text-tools')['state'] == 'running')
                    self.wait(lambda: not self.manager.bridge._busy)
                    self.assertEqual(confirmed.call_count, 1)
                    self.assertEqual(started.call_count, 1)
            finally:
                release.set()
            # A catalog refresh requested by defaults during a poll must run afterwards.
            from PySide6.QtCore import Signal
            class DefaultChanges(QObject):
                changed = Signal()
            defaults_changed = DefaultChanges()
            defaults_changed.changed.connect(self.manager.bridge.refresh)
            entered, release = threading.Event(), threading.Event()
            def block_poll():
                entered.set()
                release.wait()
                return snapshot()
            self.manager.bridge.timer.stop()
            try:
                with patch.object(self.runtime, 'snapshot', side_effect=block_poll), patch.object(sources, 'sources', wraps=sources.sources) as sampled:
                    self.manager.bridge.poll()
                    self.wait(entered.is_set)
                    defaults_changed.changed.emit()
                    self.assertTrue(self.manager.bridge._pending_refresh)
                    release.set()
                    self.wait(lambda: sampled.call_count == 1 and not self.manager.bridge._busy and not self.manager.bridge._pending_refresh)
            finally:
                release.set()
                self.manager.bridge.timer.start()
            self.click('marketDetails_org.polaris.schedule')
            self.assertTrue(self.page.findChild(QObject, 'marketDetailsDialog').property('visible'))
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            if capture: self.window.grabWindow().save(str(Path(capture) / 'market-v2-details.png'))
            self.click('closeMarketDetails')
            self.manager.bridge.dismissNotice()
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
            for width in (1300,720,360):
                self.window.resize(width,760); QTest.qWait(60)
                if capture: self.window.grabWindow().save(str(Path(capture) / ('market-v2-real-' + str(width) + '.png')))
            self.page.setProperty('marketQuery', 'ＡＧＥＮＴ 通讯')
            QTest.qWait(20)
            self.assertEqual([entry['manifest']['id'] for entry in entries()], ['org.polaris.feishu-agent'])
            if capture: self.window.grabWindow().save(str(Path(capture) / 'market-v2-search.png'))
            self.page.setProperty('marketQuery', '')
            self.page.setProperty('marketTag', '示例')
            QTest.qWait(20)
            self.assertEqual({entry['manifest']['id'] for entry in entries()}, {'org.example.text-tools','org.example.text-studio'})
            self.assertEqual(source['id'], entries()[0]['sourceId'])

        def test_git_marketplace_shows_real_catalog_states_and_installs_without_navigation(self):
            import shutil
            from polaris_platform.sources import Sources
            repo = Path(self.temp.name) / 'repo'
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL,text=True).strip()
            git('init'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
            component = repo / 'component'
            shutil.copytree(ROOT / 'examples/counter',component)
            manifest = json.loads((component / 'manifest.json').read_text())
            manifest['entry']['factory'] = 'market_counter_fixture:create'
            (component / 'counter_plugin.py').rename(component / 'market_counter_fixture.py')
            (component / 'manifest.json').write_text(json.dumps(manifest))
            descriptions = ['这是来自 Git 源的测试应用，安装后可在应用列表中打开。','本地已安装的应用，可明确选择从此源更新。']
            def application(directory, package_id, name, version):
                directory.mkdir(exist_ok=True)
                (directory / 'Main.qml').write_text('import QtQuick\nItem {}')
                (directory / 'polaris-application.json').write_text(json.dumps(dict(id=package_id,name=name,version=version,
                    entry={'adapter':'qt-quick','file':'Main.qml'},requires={})))
            application(repo / 'app','fixture.sourceapp','源应用', '1')
            application(repo / 'local','fixture.localapp','本地应用', '1')
            (repo / 'polaris-source.json').write_text(json.dumps(dict(schemaVersion=1,name='集成测试 Git 源',
                components=[dict(path='component',description='可安装的计数器示例组件。')],
                applications=[dict(path='app',description=descriptions[0]),dict(path='local',description=descriptions[1])])))
            git('add','.'); git('commit','-m','first')
            sources = Sources(self.runtime, Path(self.temp.name) / 'sources')
            self.runtime.install(dict(id='sources',name='Sources',version='1',platformApi=1,entry={'mode':'inprocess'}),lambda:sources)
            self.runtime.start_component('sources')
            control = sources.local_source_control()
            source = control.add(str(repo))
            self.open_management()
            host = self.canvas.application_host
            selected = host._selected
            local = host.installPackage(str(repo / 'local'))
            owned = host.installSourceApplication(source['id'],'fixture.sourceapp',source['revision'])
            self.assertTrue(local,host.error); self.assertTrue(owned,host.error)
            application(repo / 'app','fixture.sourceapp','源应用','2')
            git('add','.'); git('commit','-m','second')
            control.refresh(source['id'])
            self.manager.bridge.refresh(); self.wait(lambda: not self.manager.bridge._busy)
            self.page.setProperty('category','market')
            host.dismissMessage()
            QTest.qWait(40)
            source_button = find(self.window.contentItem(),'installSource_fixture.sourceapp')
            local_button = find(self.window.contentItem(),'installSource_fixture.localapp')
            component_button = find(self.window.contentItem(),'installSource_org.example.counter')
            self.assertEqual(source_button.property('text'),'更新')
            self.assertEqual(local_button.property('text'),'已安装')
            self.assertEqual(component_button.property('text'),'安装')
            self.assertEqual(host._selected,selected)
            self.assertEqual(self.runtime.status(owned)['state'],'installed')
            self.assertNotIn(owned,host._views)
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            for width in (1300,720,360):
                self.window.resize(width,760); QTest.qWait(40)
                if capture: self.window.grabWindow().save(str(Path(capture) / ('market-mixed-' + str(width) + '.png')))
            self.window.resize(1300,760)
            self.click('installSource_fixture.sourceapp')
            self.assertEqual(source_button.property('text'),'已安装')
            self.assertFalse(source_button.isEnabled())
            self.assertEqual(host._selected,selected)
            self.assertEqual(self.page.property('category'),'market')
            self.assertEqual(host.packages.load_verified(host.store.load(owned))['manifest']['version'],'2')
            self.click('changeSource_fixture.localapp')
            self.assertEqual(host._source_origins[local]['sourceId'],source['id'])
            self.assertIsNone(find(self.window.contentItem(),'sourceApplicationTarget'))
            self.click('removeSource_fixture.localapp')
            self.assertTrue(self.page.findChild(QObject, 'applicationRemovalDialog').property('visible'))
            self.click('cancelApplicationRemoval')
            self.assertTrue(host.store.load(local))
            self.click('removeSource_fixture.localapp')
            self.click('confirmApplicationRemoval')
            self.assertFalse((host.store.directory / (local + '.json')).exists())
            self.assertEqual(host._selected, selected)
            # Older imported data can contain another UUID for the same package;
            # only this real ambiguity requires an explicit target choice.
            duplicate = host.packages.install(repo / 'app')
            host._ensure_application(duplicate)
            self.runtime.register_application_bindings(duplicate.id,[])
            host.store.save(duplicate)
            host.refreshManagedApplications(); QTest.qWait(20)
            self.assertEqual(find(self.window.contentItem(),'installSource_fixture.sourceapp').property('text'),'选择应用更新…')
            self.click('installSource_fixture.sourceapp')
            confirm = find(self.window.contentItem(),'confirmSourceApplicationUpdate')
            self.assertFalse(confirm.isEnabled())
            target = find(self.window.contentItem(),'sourceApplicationTarget')
            self.assertEqual(target.property('currentIndex'),-1)
            targets = [row['applicationId'] for row in json.loads(host.managedApplicationsJson) if row.get('packageId') == 'fixture.sourceapp']
            target.setProperty('currentIndex',targets.index(duplicate.id))
            self.click('confirmSourceApplicationUpdate')
            self.assertEqual(len(host._source_origins),2)
            # Multiple installed UUIDs require selecting one, then the existing removal confirmation.
            self.click('removeSource_fixture.sourceapp')
            if capture: self.window.grabWindow().save(str(Path(capture) / 'market-multiple-removal.png'))
            removal_target = find(self.window.contentItem(), 'sourceApplicationRemovalTarget')
            self.assertEqual(removal_target.property('currentIndex'), -1)
            self.assertFalse(find(self.window.contentItem(), 'selectSourceApplicationRemoval').isEnabled())
            removal_target.setProperty('currentIndex', targets.index(duplicate.id))
            self.click('selectSourceApplicationRemoval')
            self.click('cancelApplicationRemoval')
            self.assertTrue(host.store.load(duplicate.id))
            self.click('removeSource_fixture.sourceapp')
            find(self.window.contentItem(), 'sourceApplicationRemovalTarget').setProperty('currentIndex', targets.index(duplicate.id))
            self.click('selectSourceApplicationRemoval')
            self.click('confirmApplicationRemoval')
            self.assertFalse((host.store.directory / (duplicate.id + '.json')).exists())
            self.assertTrue(host.store.load(owned))
            self.assertEqual(host._selected, selected)
            self.click('installSource_org.example.counter')
            self.wait(lambda: not self.manager.bridge.busy and find(self.window.contentItem(),'installSource_org.example.counter').property('text') == '已安装')
            component_button = find(self.window.contentItem(),'installSource_org.example.counter')
            self.assertEqual(component_button.property('text'),'已安装',(self.manager.bridge.notice,self.manager.bridge.sourcesJson,self.manager.bridge.dataJson))
            self.assertEqual(self.runtime.status('org.example.counter')['state'],'installed')
            self.assertEqual(host._selected,selected)
            self.manager.bridge.dismissNotice()
            if capture: self.window.grabWindow().save(str(Path(capture) / 'market-component-uninstall.png'))
            self.click('removeSource_org.example.counter')
            self.wait(lambda: self.manager.bridge._installation_plan is not None)
            if capture: self.window.grabWindow().save(str(Path(capture) / 'market-component-uninstall-confirm.png'))
            self.assertEqual(self.manager.bridge._installation_plan['action'], 'uninstall')
            self.click('cancelInstallation')
            self.assertEqual(self.runtime.status('org.example.counter')['state'], 'installed')
            self.click('removeSource_org.example.counter')
            self.wait(lambda: self.manager.bridge._installation_plan is not None)
            self.click('confirmInstallation')
            self.wait(lambda: all(item['manifest']['id'] != 'org.example.counter' for item in self.runtime.export_installations()))
            self.page.setProperty('marketKind','application'); QTest.qWait(20)
            self.assertIsNone(find(self.window.contentItem(),'installSource_org.example.counter'))
            self.assertIsNotNone(find(self.window.contentItem(),'installSource_fixture.sourceapp'))
            self.page.setProperty('marketSource',source['id'])
            self.manager.bridge.refresh(); self.wait(lambda: not self.manager.bridge._busy)
            QTest.qWait(20)
            filter_control = find(self.window.contentItem(),'marketSourceFilter')
            self.assertEqual(filter_control.property('currentIndex'),1)
            self.assertEqual(filter_control.property('currentText'),'集成测试 Git 源')
            self.assertEqual(find(self.window.contentItem(),'marketKindFilter').property('currentIndex'),1)
            # Explicit catalogue fixtures cover a loaded empty selected source
            # while an unrelated source is still awaiting its first refresh.
            rows = control.sources() + [dict(id='empty',name='空目录源',location='/fixture/empty',revision='loaded',components=[],applications=[]),
                dict(id='pending',name='待刷新源',location='/fixture/pending',revision=None,components=[],applications=[])]
            self.manager.bridge._sources_json = json.dumps(rows)
            self.manager.bridge.sourcesChanged.emit()
            self.page.setProperty('marketSource','empty'); QTest.qWait(20)
            self.assertTrue(find(self.window.contentItem(),'marketEmptyState').isVisible())
            self.assertEqual(filter_control.property('currentText'),'空目录源')
            self.manager.bridge.changed.emit(); QTest.qWait(20)
            self.assertEqual(filter_control.property('currentText'),'空目录源')
            # An archived selection leaves active search and falls back to the default catalog.
            rows[0]['defaultCatalog'] = True
            rows.append(dict(id='historic',name='旧来源',location='/history',revision='old',archived=True,
                             components=[dict(path='x',manifest=dict(id='historic.component',name='历史组件',version='1'))],applications=[]))
            self.page.setProperty('marketSource','historic')
            self.manager.bridge._sources_json = json.dumps(rows)
            self.manager.bridge.sourcesChanged.emit(); QTest.qWait(20)
            self.assertEqual(self.page.property('marketSource'), source['id'])
            self.assertIsNone(find(self.window.contentItem(), 'installSource_historic.component'))
            self.click('sourceButton')
            self.assertTrue(find(self.window.contentItem(), 'toggleArchivedSources').isVisible())
            self.click('toggleArchivedSources')
            if capture: self.window.grabWindow().save(str(Path(capture) / 'market-source-history.png'))
            self.assertTrue(self.page.property('showArchivedSources'))
            self.click('closeSources')

        def test_component_instances_and_native_view_authorization_overlay(self):
            import shutil
            source = Path(self.temp.name) / 'counter'
            shutil.copytree(ROOT / 'examples/counter', source)
            manifest = json.loads((source / 'manifest.json').read_text())
            manifest['instances'] = {'mode': 'multiple'}
            (source / 'manifest.json').write_text(json.dumps(manifest))
            module = source / 'counter_plugin.py'
            module.write_text(module.read_text().replace('def create():', 'def create(instance_context=None):'))
            self.runtime.install_directory(source)
            self.runtime.start_component('org.example.counter')
            self.open_management()
            self.manager.bridge.refresh()
            self.wait(lambda: not self.manager.bridge._busy)
            self.page.setProperty('category', 'components')
            self.page.setProperty('selectedId', 'org.example.counter')
            self.click('createComponentInstance')
            self.wait(lambda: not self.manager.bridge.busy and self.page.property('selectedId') != 'org.example.counter')
            identity = self.page.property('selectedId')
            self.assertEqual(self.runtime.status(identity)['state'], 'running')
            self.assertFalse(self.runtime.authorization.scope(identity))
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            for width in (1300, 360):
                self.window.resize(width, 760)
                QTest.qWait(25)
                if capture:
                    Path(capture).mkdir(parents=True, exist_ok=True)
                    self.window.grabWindow().save(str(Path(capture) / f'extensions-instances-{width}.png'))
            self.window.resize(1300, 760)
            self.click('configureComponentInstance')
            self.wait(lambda: self.manager.bridge._pending_plan is not None and not self.manager.bridge.busy)
            self.assertFalse(self.root.property('settingsOpen'))
            self.assertEqual(self.canvas.application_host._selected,
                             'f3bcb2d1737d4f4e9c57c5ea63f68209')
            self.assertTrue(find(self.window.contentItem(), 'confirmPermission').isVisible())
            if capture:
                self.window.grabWindow().save(str(Path(capture) / 'canvas-permission-overlay.png'))
            self.click('cancelPermission')
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.assertFalse(self.canvas.status()['mounts'])
            self.open_management()
            self.page.setProperty('category', 'components')
            self.page.setProperty('selectedId', identity)
            self.click('configureComponentInstance')
            self.wait(lambda: self.manager.bridge._pending_plan is not None and not self.manager.bridge.busy)
            token = self.manager.bridge._pending_plan['approvalToken']
            self.canvas.hide(self.canvas.session_context)
            self.assertEqual(self.manager.bridge._pending_plan['approvalToken'], token)
            self.open_management()
            self.wait(lambda: bool(self.canvas._holds))
            self.assertEqual(self.manager.bridge._pending_plan['approvalToken'], token)
            self.click('confirmPermission')
            self.wait(lambda: not self.manager.bridge.busy and not self.manager.bridge._approvals
                      and any(row['state'] == 'mounted' for row in self.canvas.status()['mounts']))
            self.assertFalse(self.manager.bridge._pending_plan)
            self.assertFalse(self.manager.bridge._approvals)
            self.assertFalse(self.canvas.workbench._approval_tokens)
            self.wait(lambda: 'management-permission' not in self.canvas._holds and 'overlay' not in self.canvas._holds)

    unittest.main()
