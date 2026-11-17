"""Black-box Qt interactions for canvas sessions and third-party native views."""
import os
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

if __name__ != '__main__':
    class CanvasUIProcessTests(unittest.TestCase):
        def test_real_pointer_controls_and_native_plugin_mounts(self):
            import importlib.util
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                          env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                          capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    import time
    from PySide6.QtCore import QPoint, QPointF, Qt, QEvent, QCoreApplication
    from PySide6.QtGui import QGuiApplication, QCursor, QMouseEvent, QWheelEvent
    from PySide6.QtTest import QTest

    def _mouseMove(window, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseMove(window, point)

    def _mouseClick(window, button, modifiers, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseClick(window, button, modifiers, point)

    def _mousePress(window, button, modifiers, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mousePress(window, button, modifiers, point)

    def _mouseRelease(window, button, modifiers, point):
        QCursor.setPos(window.mapToGlobal(point))
        QTest.mouseRelease(window, button, modifiers, point)
    from polaris_platform.bootstrap import build, default_config
    from polaris_platform.component import Component
    from polaris_platform.desktop import WindowHost, Canvas, Manager

    def find_item(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            result = find_item(child, name)
            if result is not None:
                return result
        return None

    class CanvasInteractionTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.app = QGuiApplication.instance() or QGuiApplication([])

        def setUp(self):
            self.runtime = build(default_config())
            self.host = WindowHost(runtime=self.runtime)
            self.canvas = Canvas(runtime=self.runtime, collapse_delay=160)
            self.manager = Manager(self.runtime)
            for identity, component in [('window', self.host), ('canvas', self.canvas), ('manager', self.manager), ('user', Component())]:
                self.runtime.install({'id': identity, 'name': identity, 'version': '1', 'platformApi': 1,
                                      'entry': {'mode': 'inprocess'}}, lambda c=component: c)
                self.runtime.start_component(identity)
            self.runtime.install_directory(ROOT / 'examples' / 'counter')
            self.runtime.start_component('org.example.counter')
            for target in ('window', 'canvas', 'org.example.counter'):
                for operation in self.runtime.status(target)['description']['operations']:
                    self.runtime.grant('user', target, operation)
            self.context = self.runtime.user_context('user')
            QCursor.setPos(self.app.primaryScreen().availableGeometry().topLeft() + QPoint(5, 5))
            self.call('canvas', 'show')
            self.window = self.host._views[self.canvas.handle]
            self.wait(lambda: self.window.isVisible())
            QTest.qWait(30)

        def tearDown(self):
            # Queued GUI work must finish before the application tears resources down.
            for _ in range(20):
                self.app.processEvents()
                QTest.qWait(5)
            for row in reversed(self.runtime.snapshot()):
                if row['state'] == 'running':
                    self.runtime.stop_component(row['id'], force=True)
            QTest.qWait(30)

        def call(self, target, operation, params=None):
            return self.runtime.client('user').call(target, operation, params, context=self.context)

        def wait(self, predicate, timeout=3):
            deadline = time.monotonic() + timeout
            while not predicate() and time.monotonic() < deadline:
                self.app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                time.sleep(.01)
            self.assertTrue(predicate(), f"session={self.canvas.session_id} entered={self.canvas._entered} inside={self.canvas._inside} holds={self.canvas._holds}")

        def click(self, name, parent=None):
            item = find_item(parent or self.window.contentItem(), name)
            self.assertIsNotNone(item, name)
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            _mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
            QTest.qWait(30)
            return item

        def mount(self):
            result = self.call('canvas', 'mount', {'target': 'org.example.counter', 'view': 'main'})
            mount_id = result['mountId']
            self.wait(lambda: any(m['mountId'] == mount_id and m['state'] == 'mounted'
                                  for m in self.canvas.status()['mounts']))
            return mount_id

        def test_preferred_sizes_are_clamped_and_theme_updates(self):
            cases = [({'width': '640', 'height': True}, (380, 340)),
                     ({'width': float('nan'), 'height': float('inf')}, (380, 340)),
                     ({'width': -1, 'height': 10 ** 400}, (240, 1200)),
                     ({'width': 640, 'height': 540}, (640, 540))]
            for preferred, expected in cases:
                result = self.call('canvas', 'mount', {'target': 'org.example.counter', 'view': 'main',
                                                       'descriptor': {'preferredSize': preferred}})
                identity = result['mountId']
                self.wait(lambda: self.canvas.workbench.mounts[identity]['state'] == 'mounted')
                record = self.canvas.workbench.mounts[identity]
                self.assertEqual((record['layout']['width'], record['layout']['height']), expected)
                parent = record['container']
                before = parent.property('polarisTheme').toVariant()['background']
                self.canvas.actions.setTheme('warm')
                self.app.processEvents()
                self.assertNotEqual(parent.property('polarisTheme').toVariant()['background'], before)
                self.canvas.actions.setTheme('light')
                self.app.processEvents()
                self.assertNotEqual(parent.property('polarisTheme').toVariant()['background'], before)
                self.canvas.actions.setTheme('dark')
                self.call('canvas', 'unmount', {'mountId': identity})
                self.wait(lambda: identity not in self.canvas.workbench.mounts)

        def test_text_cards_and_explicit_arrange_do_not_overlap(self):
            self.call('canvas', 'set_cards', {'cards': [{'title': 'One'}, {'title': 'Two'}]})
            first, second = self.mount(), self.mount()
            self.assertGreaterEqual(self.canvas.workbench.mounts[first]['layout']['y'], 168)
            self.canvas.workbench.actions.arrange(1000)
            layouts = [self.canvas.workbench.mounts[identity]['layout'] for identity in (first, second)]
            self.assertTrue(all(row['y'] >= 168 for row in layouts))
            self.assertGreaterEqual(layouts[1]['x'], layouts[0]['x'] + layouts[0]['width'])

        def test_overflow_navigation_keeps_cards_reachable_after_resize(self):
            self.window.resize(1120, 620)
            mounts = [self.mount() for _ in range(7)]
            viewport = find_item(self.window.rootObject(), 'canvasViewport')
            self.assertIsNotNone(viewport)

            def card_for(identity):
                def visit(item):
                    if item.objectName() == 'canvasViewCard' and item.property('mountId') == identity:
                        return item
                    for child in item.childItems():
                        found = visit(child)
                        if found is not None:
                            return found
                return visit(self.window.rootObject())

            def title_visible(card):
                caption = find_item(card, 'canvasViewCaption')
                point = caption.mapToScene(QPointF(1, caption.height() / 2))
                return 12 <= point.x() < self.window.width() - 24 and 56 <= point.y() < self.window.height() - 24

            last = card_for(mounts[-1])
            original_y = self.canvas.workbench.mounts[mounts[-1]]['layout']['y']
            self.wait(lambda: viewport.property('contentY') > 0 and title_visible(last))
            self.assertEqual(last.y(), original_y, 'Scrolling must preserve the logical card layout')
            self.assertEqual((last.width(), last.height()), (380, 340), 'New native cards must leave useful space for their content')
            self.assertEqual(viewport.property('contentWidth'), viewport.width())
            self.assertFalse(find_item(self.window.rootObject(), 'canvasHorizontalScroll').isVisible())
            self.window.resize(380, 280)
            self.wait(lambda: viewport.width() == self.window.width() - self.window.rootObject().property('navigationWidth') - 32 and viewport.height() == self.window.height() - 102)
            self.assertGreater(viewport.property('contentWidth'), viewport.width())
            self.assertGreater(viewport.property('contentHeight'), viewport.height())

            def drag_scrollbar(name, end):
                bar = find_item(self.window.rootObject(), name)
                self.assertTrue(bar.isVisible())
                vertical = name == 'canvasVerticalScroll'
                length = bar.property('availableHeight') if vertical else bar.property('availableWidth')
                padding = bar.property('topPadding') if vertical else bar.property('leftPadding')
                visual_size = bar.property('visualSize')
                center = padding + (bar.property('visualPosition') + visual_size / 2) * length
                target = padding + (end * (1 - visual_size) + visual_size / 2) * length
                start = QPointF(bar.width() / 2, center) if vertical else QPointF(center, bar.height() / 2)
                finish = QPointF(bar.width() / 2, target) if vertical else QPointF(target, bar.height() / 2)
                start, finish = bar.mapToScene(start).toPoint(), bar.mapToScene(finish).toPoint()
                _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
                for step in range(1, 6):
                    _mouseMove(self.window, start + (finish - start) * step / 5)
                    QTest.qWait(10)
                _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, finish)
                QTest.qWait(30)

            # Both axes must be usable by pointer even when a native card is
            # wider than the window. Its own content still receives clicks.
            drag_scrollbar('canvasVerticalScroll', 0)
            drag_scrollbar('canvasHorizontalScroll', 1)
            second = card_for(mounts[1])
            self.wait(lambda: title_visible(second))
            # A new card is taller than this viewport. Navigate to its native
            # content by the real scrollbar, then return to its header.
            drag_scrollbar('canvasVerticalScroll', 0.12)
            increase = find_item(second, 'counterIncrease')
            point = increase.mapToScene(QPointF(increase.width() / 2, increase.height() / 2))
            self.assertTrue(64 <= point.y() < self.window.height() - 12)
            self.click('counterIncrease', parent=second)
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})
            drag_scrollbar('canvasVerticalScroll', 0)
            self.wait(lambda: title_visible(second))
            self.click('canvasCollapseView', parent=second)
            self.assertTrue(second.property('collapsed'))
            before = next(row['layout'] for row in self.canvas.status()['mounts'] if row['mountId'] == mounts[1])
            start = second.mapToScene(QPointF(100, 20)).toPoint()
            _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
            _mouseMove(self.window, start + QPoint(-30, 30))
            _mouseMove(self.window, start + QPoint(-50, 50))
            _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, start + QPoint(-50, 50))
            self.wait(lambda: next(row['layout'] for row in self.canvas.status()['mounts'] if row['mountId'] == mounts[1]) != before)
            self.assertEqual(self.canvas.workbench.mounts[mounts[1]]['layout']['collapsed'], True)
            drag_scrollbar('canvasHorizontalScroll', 0)
            drag_scrollbar('canvasVerticalScroll', 1)
            # This card is taller than the shrunken viewport. A background
            # wheel event can move back from its bottom to reach its title.
            point = QPoint(90, 150)
            self.app.sendEvent(self.window, QWheelEvent(QPointF(point), QPointF(self.window.mapToGlobal(point)),
                QPoint(), QPoint(0, 540), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
            self.wait(lambda: title_visible(last))
            self.app.sendEvent(self.window, QWheelEvent(QPointF(point), QPointF(self.window.mapToGlobal(point)),
                QPoint(), QPoint(0, -480), Qt.NoButton, Qt.ShiftModifier, Qt.NoScrollPhase, False))
            self.wait(lambda: viewport.property('contentX') > 0)
            close = find_item(last, 'canvasUnmountView')
            point = close.mapToScene(QPointF(close.width() / 2, close.height() / 2))
            self.assertTrue(84 <= point.x() < self.window.width() - 12 and 102 <= point.y() < self.window.height() - 12, (point.x(), point.y(), viewport.property('contentX'), viewport.property('contentY')))
            self.click('canvasUnmountView', parent=last)
            self.wait(lambda: mounts[-1] not in self.canvas.workbench.mounts)

        def test_first_show_pointer_delay_cancel_and_popup_hold(self):
            # A window-leave notification before the first entry is not a dismissal.
            self.app.sendEvent(self.window, QEvent(QEvent.Leave))
            QTest.qWait(240)
            self.assertTrue(self.window.isVisible())
            _mouseMove(self.window, QPoint(350, 300))
            QTest.qWait(30)
            _mouseMove(self.window, QPoint(-20, -20))
            QTest.qWait(70)
            _mouseMove(self.window, QPoint(350, 300))
            QTest.qWait(220)
            self.assertTrue(self.window.isVisible(), 'Reentering must cancel pending dismissal')
            self.click('chooseComponentView')
            _mouseMove(self.window, QPoint(-20, -20))
            QTest.qWait(240)
            self.assertTrue(self.window.isVisible(), 'An open popup holds the canvas')
            QTest.keyClick(self.window, Qt.Key_Escape)
            _mouseMove(self.window, QPoint(350, 300))
            _mouseMove(self.window, QPoint(-20, -20))
            self.wait(lambda: not self.window.isVisible())

        def test_plugin_buttons_collapse_unmount_and_provider_restart(self):
            mount_id = self.mount()
            self.click('counterIncrease')
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})
            self.click('canvasCollapseView')
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})
            self.assertEqual(self.runtime.status('org.example.counter')['state'], 'running')
            self.click('canvasCollapseView')
            self.runtime.revoke('user', 'org.example.counter', 'increment')
            self.click('counterIncrease')
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})
            self.call('canvas', 'unmount', {'mountId': mount_id})
            self.wait(lambda: not self.canvas.status()['mounts'])
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})
            self.mount()
            self.runtime.stop_component('org.example.counter')
            self.wait(lambda: not self.canvas.status()['mounts'])
            self.runtime.start_component('org.example.counter')
            self.mount()
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 0})

        def test_revoked_window_hide_does_not_claim_dismissal(self):
            session = self.canvas.status()['sessionId']
            self.runtime.revoke('user', 'window', 'hide')
            _mouseMove(self.window, QPoint(350, 300))
            _mouseMove(self.window, QPoint(-20, -20))
            QTest.qWait(350)
            self.assertTrue(self.window.isVisible())
            self.assertEqual(self.canvas.status()['sessionId'], session)

        def test_restricted_unmount_cannot_borrow_creating_requests_release_permission(self):
            mount_id = self.mount()
            self.click('counterIncrease')
            provider = self.runtime.component_instance('org.example.counter')
            release_calls = []
            original = provider._handlers['release_view']
            def audit_release(params, context):
                release_calls.append(True)
                return original(params, context)
            provider._handlers['release_view'] = audit_release
            self.runtime.install({'id': 'limited', 'name': 'Limited', 'version': '1', 'platformApi': 1,
                                  'entry': {'mode': 'inprocess'}}, Component)
            self.runtime.start_component('limited')
            self.runtime.grant('limited', 'canvas', 'unmount')
            result = self.runtime.client('limited').call('canvas', 'unmount', {'mountId': mount_id},
                                                       context=self.runtime.user_context('limited'))
            self.assertTrue(result['released'])
            self.wait(lambda: find_item(self.window.rootObject(), 'counterView') is None)
            self.assertEqual(release_calls, [], 'A narrower unmount cannot reuse the old broad provider permission')
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})

        def prepare_approval(self):
            session = self.canvas.status()['sessionId']
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.click('chooseComponentView')
            self.wait(lambda: find_item(self.window.contentItem(), 'componentViewChoice') is not None)
            self.click('componentViewChoice')
            self.wait(lambda: not self.manager.bridge.busy and bool(self.manager.bridge.planJson)
                      and self.manager.bridge.planJson != '[]')
            self.wait(lambda: find_item(self.window.contentItem(), 'confirmPermission') is not None)
            _mouseMove(self.window, QPoint(-20, -20))
            QTest.qWait(280)
            self.assertTrue(self.window.isVisible(), 'An external permission confirmation must hold the canvas')
            self.assertEqual(self.canvas.status()['sessionId'], session)
            self.assertFalse(self.runtime.authorization.scope('canvas'), 'Choosing a view must not grant permissions')
            self.assertFalse(self.canvas.status()['mounts'])

        def approval_click(self, name):
            button = find_item(self.window.contentItem(), name)
            self.assertIsNotNone(button)
            point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
            _mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))

        def leave_canvas(self):
            _mouseMove(self.window, QPoint(350, 300))
            _mouseMove(self.window, QPoint(-20, -20))
            self.wait(lambda: not self.window.isVisible())

        def test_picker_requires_explicit_manager_confirmation_before_mounting(self):
            self.prepare_approval()
            self.approval_click('confirmPermission')
            self.wait(lambda: bool(self.canvas.status()['mounts'])
                      and self.canvas.status()['mounts'][0]['state'] == 'mounted')
            self.assertTrue(self.runtime.authorization.scope('canvas'))
            self.click('counterIncrease')
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 1})
            self.leave_canvas()  # Confirmation finished: its hold must no longer prevent leave.

        def test_cancelling_external_approval_grants_nothing_and_releases_hold(self):
            self.prepare_approval()
            self.approval_click('cancelPermission')
            self.wait(lambda: self.manager.bridge.planJson == '[]')
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.assertFalse(self.canvas.status()['mounts'])
            self.leave_canvas()

        def test_old_approval_cannot_act_on_replacement_canvas_instance(self):
            self.prepare_approval()
            previous = self.runtime.status('canvas')['instance']
            self.runtime.replace_component('canvas', self.runtime.status('canvas')['manifest'],
                                           lambda: Canvas(runtime=self.runtime, collapse_delay=160))
            replacement = self.runtime.component_instance('canvas')
            self.assertNotEqual(previous, self.runtime.status('canvas')['instance'])
            self.wait(lambda: not self.manager.bridge.busy and self.manager.bridge.planJson == '[]')
            self.assertIsNone(replacement.actions._window)
            self.assertFalse(replacement.status()['mounts'])
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.assertFalse(self.runtime.component_instance('org.example.counter')._views)

        def test_actual_frameless_handles_move_and_resize_all_eight_directions(self):
            from unittest.mock import patch
            with patch.object(self.window, 'startSystemMove', return_value=False):
                initial = self.window.position()
                _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(100, 25))
                _mouseMove(self.window, QPoint(125, 40))
                self.assertEqual(self.window.position(), initial + QPoint(25, 15))
                _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(100, 25))
            for name, dx, dy in (('Left', -20, 0), ('Right', 20, 0), ('Top', 0, -20), ('Bottom', 0, 20),
                                 ('TopLeft', -20, -20), ('TopRight', 20, -20),
                                 ('BottomLeft', -20, 20), ('BottomRight', 20, 20)):
                with self.subTest(handle=name), patch.object(self.window, 'startSystemResize', return_value=False):
                    item = find_item(self.window.rootObject(), 'canvasResize' + name)
                    self.assertIsNotNone(item)
                    center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    start = QPoint(round(center.x()), round(center.y()))
                    initial = self.window.geometry()
                    _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
                    _mouseMove(self.window, start + QPoint(dx, dy))
                    self.assertEqual(self.window.width(), initial.width() + abs(dx))
                    self.assertEqual(self.window.height(), initial.height() + abs(dy))
                    QTest.qWait(220)
                    self.assertTrue(self.window.isVisible())
                    outside = QPoint(-40, -40)
                    _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, outside)
                    QTest.qWait(70)
                    self.assertTrue(self.window.isVisible())
                    self.wait(lambda: not self.window.isVisible())
                    self.call('canvas', 'show')
                    self.wait(lambda: self.window.isVisible())

        def test_theme_bridge_notifies_and_restores_after_restart(self):
            import tempfile
            from PySide6.QtTest import QSignalSpy
            with tempfile.TemporaryDirectory() as directory:
                canvas = Canvas(data_dir=directory)
                spy = QSignalSpy(canvas.actions.themeChanged)
                self.assertEqual(canvas.actions.theme, 'dark')
                canvas.actions.setTheme('warm')
                self.assertEqual(spy.count(), 1)
                self.assertEqual(Canvas(data_dir=directory).actions.theme, 'warm')
                canvas.actions.setTheme('invalid')
                self.assertEqual(canvas.actions.theme, 'warm')
                self.assertEqual(spy.count(), 1)

        def test_native_grab_cancellation_keeps_hold_until_actual_release(self):
            from unittest.mock import patch
            with patch.object(self.window, 'startSystemMove', return_value=True):
                _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(100, 25))
                self.canvas.actions.cancelWindowGesture()
                _mouseMove(self.window, QPoint(-40, -40))
                QTest.qWait(300)
                self.assertTrue(self.window.isVisible())
                self.assertIn('native-frame', self.canvas._holds)
                _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(-40, -40))
                QTest.qWait(70)
                self.assertTrue(self.window.isVisible())
                self.wait(lambda: not self.window.isVisible())

        def test_window_gesture_system_api_success_and_fallback(self):
            from unittest.mock import patch
            actions = self.canvas.actions
            origin = self.window.position()
            start = self.window.mapToGlobal(QPoint(100, 25))
            with patch.object(self.window, 'startSystemMove', return_value=True) as native:
                actions.beginWindowGesture(0, start.x(), start.y())
                actions.updateWindowGesture(start.x() + 30, start.y() + 20)
                self.assertEqual(self.window.position(), origin)
                native.assert_called_once()
                actions.cancelWindowGesture()
                self.assertIn('native-frame', self.canvas._holds)
                self.assertIsNotNone(actions._gesture)
                actions.endWindowGesture()
            with patch.object(self.window, 'startSystemMove', return_value=False):
                actions.beginWindowGesture(0, start.x(), start.y())
                actions.updateWindowGesture(start.x() + 30, start.y() + 20)
                self.assertEqual(self.window.position(), origin + QPoint(30, 20))
                actions.endWindowGesture()
            def release_during_system_move():
                actions.endWindowGesture()
                return True
            with patch.object(self.window, 'startSystemMove', side_effect=release_during_system_move):
                actions.beginWindowGesture(0, start.x(), start.y())
                self.assertIsNone(actions._gesture)
                self.assertNotIn('native-frame', self.canvas._holds)
            for native_result in (True, False):
                initial = self.window.geometry()
                with patch.object(self.window, 'startSystemResize', return_value=native_result) as native:
                    actions.beginWindowGesture(Qt.RightEdge.value, start.x(), start.y())
                    actions.updateWindowGesture(start.x() + 30, start.y())
                    self.assertEqual(self.window.width(), initial.width() + (0 if native_result else 30))
                    native.assert_called_once_with(Qt.RightEdge)
                    actions.endWindowGesture()

        def test_frame_hover_and_release_inside_keep_canvas_open(self):
            _mouseMove(self.window, QPoint(350, 300))
            frame_point = self.window.frameGeometry().topLeft()
            self.assertTrue(self.window.geometry().contains(frame_point))
            self.assertTrue(self.window.flags() & Qt.FramelessWindowHint)
            self.assertEqual(self.window.color().alpha(), 0)
            QCursor.setPos(frame_point)
            self.app.sendEvent(self.window, QEvent(QEvent.Leave))
            QTest.qWait(500)
            self.assertTrue(self.window.isVisible(), 'The native frame is part of the canvas window')
            local = QPointF(self.window.mapFromGlobal(frame_point))
            for kind, button, buttons in (
                    (QEvent.NonClientAreaMouseButtonPress, Qt.LeftButton, Qt.LeftButton),
                    (QEvent.NonClientAreaMouseButtonRelease, Qt.LeftButton, Qt.NoButton)):
                self.app.sendEvent(self.window, QMouseEvent(kind, local, QPointF(frame_point),
                                                           button, buttons, Qt.NoModifier))
            QTest.qWait(240)
            self.assertTrue(self.window.isVisible())
            self.assertNotIn('native-frame', self.canvas._holds)
            _mouseMove(self.window, QPoint(-30, -30))
            self.wait(lambda: not self.window.isVisible())

        def test_queued_pointer_dismissal_is_cancelled_by_drag_or_reentry(self):
            _mouseMove(self.window, QPoint(350, 300))
            _mouseMove(self.window, QPoint(-30, -30))
            queued = []
            original = self.canvas.work
            self.canvas.work = queued.append
            try:
                self.canvas.dismiss_async('pointer_left')
                self.canvas.hold('drag-test', True)
                queued.pop()()
                self.assertTrue(self.window.isVisible())
                self.canvas.hold('drag-test', False)
                self.canvas.dismiss_async('pointer_left')
                _mouseMove(self.window, QPoint(350, 300))
                queued.pop()()
                self.assertTrue(self.window.isVisible())
            finally:
                self.canvas.work = original

        def test_native_frame_drag_holds_then_releases_outside_with_full_delay(self):
            _mouseMove(self.window, QPoint(350, 300))
            local = QPointF(40, -1)
            def native(kind, button, buttons):
                event = QMouseEvent(kind, local, QPointF(self.window.mapToGlobal(QPoint(40, -1))),
                                    button, buttons, Qt.NoModifier)
                self.app.sendEvent(self.window, event)
            _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(350, 300))
            native(QEvent.NonClientAreaMouseButtonPress, Qt.LeftButton, Qt.LeftButton)
            _mouseMove(self.window, QPoint(-30, -30))
            QTest.qWait(500)
            self.assertTrue(self.window.isVisible(), 'Native frame dragging must hold the canvas')
            _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(-30, -30))
            native(QEvent.NonClientAreaMouseButtonRelease, Qt.LeftButton, Qt.NoButton)
            QTest.qWait(70)
            self.assertTrue(self.window.isVisible(), 'Release outside starts a fresh collapse delay')
            self.wait(lambda: not self.window.isVisible())

        def test_resize_edge_client_press_holds_until_release(self):
            _mouseMove(self.window, QPoint(350, 300))
            # Some window systems deliver an ordinary press for the resize grab.
            _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(0, 150))
            _mouseMove(self.window, QPoint(-8, 150))
            self.window.resize(self.window.width() + 10, self.window.height())
            QTest.qWait(400)
            self.assertTrue(self.window.isVisible(), 'Resize outside the frame must hold the canvas')
            _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(-30, 150))
            QTest.qWait(70)
            self.assertTrue(self.window.isVisible())
            self.wait(lambda: not self.window.isVisible())

        def test_resize_grabs_on_each_edge_and_corner_release_inside(self):
            for horizontal, vertical in ((0, .5), (1, .5), (.5, 0), (.5, 1),
                                         (0, 0), (1, 0), (0, 1), (1, 1)):
                with self.subTest(horizontal=horizontal, vertical=vertical):
                    width, height = self.window.width(), self.window.height()
                    start = QPoint(round(horizontal * (width - 1)), round(vertical * (height - 1)))
                    outside = QPoint(-8 if horizontal == 0 else width + 8 if horizontal == 1 else width // 2,
                                     -8 if vertical == 0 else height + 8 if vertical == 1 else height // 2)
                    _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
                    _mouseMove(self.window, outside)
                    self.window.resize(width + 2, height + 2)
                    QTest.qWait(200)
                    self.assertTrue(self.window.isVisible())
                    _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(350, 300))
                    QTest.qWait(180)
                    self.assertTrue(self.window.isVisible())
                    self.assertNotIn('native-frame', self.canvas._holds)

        def test_resize_without_nonclient_press_holds_and_release_inside_stays(self):
            from PySide6.QtGui import QWindow
            other = QWindow()
            other.resize(40, 40)
            other.show()
            try:
                _mouseMove(self.window, QPoint(350, 300))
                # Model a compositor resize: no press reaches the canvas QWindow.
                _mousePress(other, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
                QCursor.setPos(self.window.mapToGlobal(QPoint(-8, -8)))
                self.window.resize(self.window.width() + 10, self.window.height() + 10)
                QTest.qWait(400)
                self.assertTrue(self.window.isVisible())
                _mouseRelease(other, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
                QCursor.setPos(self.window.mapToGlobal(QPoint(350, 300)))
                QTest.qWait(250)
                self.assertTrue(self.window.isVisible())
                self.assertNotIn('native-frame', self.canvas._holds)
                # Pressing another window alone cannot hold the canvas open.
                _mousePress(other, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
                _mouseMove(self.window, QPoint(-30, -30))
                self.wait(lambda: not self.window.isVisible())
                _mouseRelease(other, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
                self.call('canvas', 'show')
                self.wait(lambda: self.window.isVisible())
                _mouseMove(self.window, QPoint(350, 300))
                # A geometry change without a mouse press must recheck containment.
                self.window.setPosition(QCursor.pos() + QPoint(100, 100))
                self.wait(lambda: not self.window.isVisible())
            finally:
                other.close()

        def test_actual_card_drag_updates_only_layout_and_holds_canvas(self):
            mount_id = self.mount()
            header = find_item(self.window.rootObject(), 'canvasViewHeader')
            start = header.mapToScene(QPointF(40, 20))
            start = QPoint(round(start.x()), round(start.y()))
            _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, start)
            for delta in (15, 40, 75):
                _mouseMove(self.window, start + QPoint(delta, delta // 2))
                QTest.qWait(20)
            outside = QPoint(self.window.width() + 25, 300)
            _mouseMove(self.window, outside)
            QTest.qWait(220)
            self.assertTrue(self.window.isVisible(), 'Dragging beyond the canvas edge must suppress dismissal')
            _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, outside)
            QTest.qWait(30)
            layout = next(m['layout'] for m in self.canvas.status()['mounts'] if m['mountId'] == mount_id)
            self.assertGreater(layout['x'], 24)
            self.assertEqual(self.call('org.example.counter', 'get'), {'value': 0})

        def test_single_view_concurrent_mounts_reuse_and_recheck_authority(self):
            import threading
            from polaris_platform.protocol import PlatformError
            provider = self.runtime.component_instance('org.example.counter')
            provider.views[0]['instancePolicy'] = 'single'
            provider.port.advertise()
            barrier = threading.Barrier(5)
            results, errors = [], []
            def mount():
                try:
                    barrier.wait(timeout=3)
                    results.append(self.call('canvas', 'mount', {'target': 'org.example.counter', 'view': 'main'}))
                except Exception as error:
                    errors.append(error)
            threads = [threading.Thread(target=mount) for _ in range(5)]
            for thread in threads: thread.start()
            self.wait(lambda: all(not thread.is_alive() for thread in threads), timeout=8)
            self.assertFalse(errors, errors)
            self.assertEqual(len({result['mountId'] for result in results}), 1)
            mount_id = results[0]['mountId']
            self.wait(lambda: self.canvas.workbench.mounts[mount_id]['state'] == 'mounted')
            self.assertEqual(len(provider._views), 1)
            self.call('canvas', 'layout', {'mountId': mount_id, 'collapsed': True})
            self.call('canvas', 'hide')
            result = self.call('canvas', 'mount', {'target': 'org.example.counter', 'view': 'main'})
            self.assertTrue(result['reused'])
            self.assertTrue(self.window.isVisible())
            self.assertFalse(self.canvas.workbench.mounts[mount_id]['layout']['collapsed'])
            self.runtime.revoke('user', 'org.example.counter', 'create_view')
            with self.assertRaises(PlatformError) as caught:
                self.call('canvas', 'mount', {'target': 'org.example.counter', 'view': 'main'})
            self.assertEqual(caught.exception.code, 'permission_required')
            self.assertEqual(len(provider._views), 1)

        def test_pointer_overlay_timer_stops_hidden_and_resumes_shown(self):
            import json
            from PySide6.QtCore import QObject
            from PySide6.QtTest import QSignalSpy
            timer = self.window.rootObject().findChild(QObject, 'canvasPointerOverlayTimer')
            self.assertIsNotNone(timer)
            self.assertEqual(timer.property('interval'), 80)
            spy = QSignalSpy(timer.triggered)
            _mouseMove(self.window, QPoint(350, 300))
            before = spy.count()
            QTest.qWait(320)
            visible_ticks = spy.count() - before
            self.assertGreaterEqual(visible_ticks, 2)
            self.call('canvas', 'hide')
            self.wait(lambda: not self.window.isVisible())
            QTest.qWait(20)
            before = spy.count()
            QTest.qWait(320)
            hidden_ticks = spy.count() - before
            self.assertEqual(hidden_ticks, 0)
            self.assertFalse(timer.property('running'))
            self.call('canvas', 'show')
            self.wait(lambda: self.window.isVisible())
            _mouseMove(self.window, QPoint(350, 300))
            before = spy.count()
            QTest.qWait(320)
            resumed_ticks = spy.count() - before
            self.assertGreaterEqual(resumed_ticks, 2)
            self.call('canvas', 'hide')
            self.wait(lambda: not self.window.isVisible())
            # Reproduce the old running:true policy on this isolated, hidden
            # QML timer, after validating the real new visibility binding.
            timer.setProperty('running', True)
            before = spy.count()
            QTest.qWait(320)
            old_policy_hidden_ticks = spy.count() - before
            self.assertGreaterEqual(old_policy_hidden_ticks, 2)
            timer.setProperty('running', False)
            evidence = dict(window='isolated offscreen Qt', intervalMs=80, sampleWindowMs=320,
                visibleTicks=visible_ticks, hiddenTicksAfterFix=hidden_ticks,
                shownAgainTicks=resumed_ticks, hiddenTicksWithOldRunningTrue=old_policy_hidden_ticks,
                baselineMethod='Replay original running:true policy on the same isolated timer after fixed-policy assertions')
            destination = os.environ.get('POLARIS_TIMER_EVIDENCE')
            if destination:
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')

        def test_hidden_workbench_editor_does_not_receive_keyboard_input(self):
            from PySide6.QtCore import QUrl, QMetaObject
            from PySide6.QtQml import QQmlComponent, qmlEngine
            self.mount()
            parent = find_item(self.window.rootObject(), 'componentViewContent')
            component = QQmlComponent(qmlEngine(parent))
            component.setData(b'import QtQuick\nTextInput { width: 140; height: 32; text: "focus"; property int keyEvents: 0; Keys.onReturnPressed: keyEvents += 1 }', QUrl())
            editor = component.create()
            self.assertIsNotNone(editor, [error.toString() for error in component.errors()])
            editor.setParent(parent)
            editor.setParentItem(parent)
            editor.forceActiveFocus()
            QTest.keyClick(self.window, Qt.Key_Return)
            self.assertEqual(editor.property('keyEvents'), 1)
            self.assertTrue(QMetaObject.invokeMethod(self.window.rootObject(), 'showSettings', Qt.DirectConnection))
            QTest.keyClick(self.window, Qt.Key_Return)
            self.assertEqual(editor.property('keyEvents'), 1)
            self.assertFalse(find_item(self.window.rootObject(), 'canvasViewport').isEnabled())
            self.click('workspaceEntry')
            self.assertTrue(find_item(self.window.rootObject(), 'canvasViewport').isEnabled())
            point = editor.mapToScene(QPointF(20, 12)).toPoint()
            _mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
            QTest.keyClick(self.window, Qt.Key_Return)
            self.assertEqual(editor.property('keyEvents'), 2)

        def test_canvas_keyboard_reveals_navigation_and_appearance(self):
            import tempfile
            from PySide6.QtCore import QMetaObject
            with tempfile.TemporaryDirectory() as directory:
                host = self.canvas.application_host
                host.configure(directory)
                identities = []
                for n in range(8):
                    package = Path(directory) / ('pkg' + str(n))
                    package.mkdir()
                    (package / 'Main.qml').write_text('import QtQuick\nItem {}')
                    (package / 'polaris-application.json').write_text(json.dumps({
                        'id': 'fixture.navigation' + str(n), 'name': '<b>很长的应用名称</b>' + str(n), 'version': '1',
                        'entry': {'adapter': 'qt-quick', 'file': 'Main.qml'}, 'requires': {}}))
                    host.installDirectory(str(package))
                    identities.append(json.loads(host.selectedJson)['applicationId'])
                host.dismissMessage()
                self.window.resize(360, 280); QTest.qWait(60)
                root = self.window.rootObject()
                rail = find_item(root, 'canvasApplicationRail')
                first = find_item(root, 'workspaceEntry')
                first.forceActiveFocus(Qt.TabFocusReason)
                for _ in range(8):
                    QTest.keyClick(self.window, Qt.Key_Tab); QTest.qWait(20)
                    focus = self.window.activeFocusItem()
                    self.assertTrue(focus.objectName().startswith('applicationEntry_'), focus.objectName())
                    top = focus.mapToItem(rail, QPointF(0, 0)).y()
                    self.assertGreaterEqual(top, -0.5)
                    self.assertLessEqual(top + focus.height(), rail.height() + 0.5)
                    self.assertTrue(focus.property('hintVisible'))
                title = find_item(root, 'canvasPageTitle')
                self.assertIn('<b>', title.property('text'))
                self.assertTrue(title.property('truncated'))
                capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
                if capture:
                    Path(capture).mkdir(parents=True, exist_ok=True)
                    QTest.qWait(700)
                    self.window.grabWindow().save(str(Path(capture) / 'canvas-navigation-focus-360x280.png'))
                QMetaObject.invokeMethod(root, 'showSettings', Qt.DirectConnection)
                QTest.qWait(20)
                appearance = find_item(root, 'canvasAppearancePage')
                dark = find_item(root, 'canvasAppearance_dark')
                warm = find_item(root, 'canvasAppearance_warm')
                dark.forceActiveFocus(Qt.TabFocusReason)
                for _ in range(2):
                    QTest.keyClick(self.window, Qt.Key_Tab); QTest.qWait(20)
                self.assertEqual(self.window.activeFocusItem(), warm)
                top = warm.mapToItem(appearance, QPointF(0, 0)).y()
                self.assertGreaterEqual(top, -0.5)
                if warm.height() <= appearance.height():
                    self.assertLessEqual(top + warm.height(), appearance.height() + 0.5)
                else:
                    self.assertLessEqual(top, 0.5)
                dismiss = find_item(root, 'dismissCanvas')
                dismiss.forceActiveFocus(Qt.TabFocusReason); QTest.qWait(20)
                self.assertTrue(dismiss.property('hintVisible'))
                QTest.qWait(700)
                capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
                if capture:
                    Path(capture).mkdir(parents=True, exist_ok=True)
                    self.window.grabWindow().save(str(Path(capture) / 'canvas-keyboard-focus-360x280.png'))
                root.setProperty('settingsOpen', False)
                host.select(identities[-1]); QTest.qWait(20)
                from unittest.mock import patch
                point = title.mapToScene(QPointF(8, 8)).toPoint()
                _mouseMove(self.window, point); QTest.qWait(700)
                if capture:
                    self.window.grabWindow().save(str(Path(capture) / 'canvas-title-hint-360x280.png'))
                with patch.object(self.window, 'startSystemMove', return_value=False):
                    initial = self.window.position()
                    _mousePress(self.window, Qt.LeftButton, Qt.NoModifier, point)
                    _mouseMove(self.window, point + QPoint(20, 10))
                    self.assertEqual(self.window.position(), initial + QPoint(20, 10))
                    _mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, point)

        def test_canvas_feedback_layout_and_keyboard(self):
            import tempfile
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
            root = self.window.rootObject()
            host = self.canvas.application_host
            with tempfile.TemporaryDirectory() as directory:
                host.configure(directory)
                package = Path(directory) / 'fixture'
                package.mkdir()
                (package / 'Main.qml').write_text('import QtQuick\nItem {}')
                (package / 'polaris-application.json').write_text(json.dumps({
                    'id': 'fixture.canvas-messages', 'name': '消息验收应用', 'version': '1',
                    'entry': {'adapter': 'qt-quick', 'file': 'Main.qml'}, 'requires': {}}))
                host.installDirectory(str(package))
                self.assertFalse(host.error, host.error)
                selected = json.loads(host.selectedJson)['applicationId']
                message = find_item(root, 'canvasMessageBar')
                label = find_item(root, 'canvasMessageText')
                close = find_item(root, 'canvasCloseMessage')
                content = find_item(root, 'customApplicationSurface')
                for width in (1300, 720, 620, 619, 360):
                    self.window.resize(width, 760)
                    QTest.qWait(30)
                    self.assertFalse(message.isVisible(), 'Packaged application feedback belongs in its connection dialog')
                    self.assertEqual(content.y(), root.property('contentTop'))
                    self.assertEqual(content.y(), 90)
                    if capture:
                        self.window.grabWindow().save(str(Path(capture) / f'installed-{width}.png'))
                host._notice = '安装失败：这是新错误，必须优先显示。' * 30
                host.changed.emit()
                QTest.qWait(30)
                self.assertEqual(label.property('text'), host._notice)
                scroll = find_item(root, 'canvasMessageScroll')
                self.assertGreater(label.height(), scroll.height(), 'Long errors remain scrollable')
                self.assertGreater(content.height(), 200)
                self.assertTrue(close.isVisible())
                flick = scroll.property('contentItem')
                flick.setProperty('contentY', flick.property('contentHeight') - flick.height())
                self.assertGreater(flick.property('contentY'), 0)
                self.assertEqual(label.property('text'), host._notice, 'Scrolling keeps the complete error text')
                if capture:
                    self.window.grabWindow().save(str(Path(capture) / 'error-long-360.png'))
                close.forceActiveFocus(Qt.TabFocusReason)
                self.assertTrue(close.property('visualFocus'))
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                self.assertFalse(message.isVisible())
                self.assertFalse(host.feedback, 'Closing the error must not revive old success')
                host._run_app = selected
                host._generation += 1
                host._state, host._error = 'error', '运行失败，关闭消息后仍保留执行结果'
                host.changed.emit()
                QTest.qWait(20)
                self.click('canvasCloseMessage')
                self.assertEqual((host.state, host.error), ('error', '运行失败，关闭消息后仍保留执行结果'))
                settings = find_item(root, 'canvasSettingsEntry')
                settings.forceActiveFocus(Qt.TabFocusReason)
                self.assertTrue(settings.property('visualFocus'))
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                self.assertTrue(root.property('settingsOpen'))
                self.assertFalse(message.isVisible())
                for width in (1300, 720, 620, 619, 360):
                    self.window.resize(width, 760)
                    QTest.qWait(30)
                    themes = [find_item(root, 'canvasAppearance_' + key) for key in ('dark', 'light', 'warm')]
                    page = find_item(root, 'canvasSettingsPage')
                    for theme in themes:
                        self.assertLessEqual(theme.mapToScene(QPointF(theme.width(), 0)).x(), width - 12)
                    if width == 360:
                        self.assertGreater(themes[1].y(), themes[0].y())
                    if capture:
                        self.window.grabWindow().save(str(Path(capture) / f'settings-{width}.png'))
                theme = find_item(root, 'canvasAppearance_warm')
                theme.forceActiveFocus(Qt.TabFocusReason)
                self.assertTrue(theme.property('visualFocus'))
                from PySide6.QtQml import QQmlProperty
                self.assertEqual(QQmlProperty(theme.property('background'), 'border.width').read(), 2)
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                self.assertEqual(self.canvas.actions.theme, 'warm')
                if capture:
                    self.window.grabWindow().save(str(Path(capture) / 'theme-keyboard-focus-360.png'))
                for _ in range(18):
                    QTest.keyClick(self.window, Qt.Key_Tab)
                    focused = self.window.activeFocusItem()
                    self.assertIsNotNone(focused)
                    self.assertTrue(focused.isVisible(), focused.objectName())
                    self.assertTrue(focused.isEnabled(), focused.objectName())
                # Removing an application leaves an empty page; entering settings is
                # still navigation even though the selected application stays ''.
                self.click('applicationEntry_' + selected)
                self.click('applicationConnectionsToggle')
                host._state = 'running'
                host.changed.emit()
                QTest.qWait(20)
                busy = find_item(self.window.contentItem(), 'applicationBusyMessage')
                self.assertLessEqual(busy.mapToScene(QPointF(busy.width(), 0)).x(), self.window.width() - 24)
                if capture:
                    self.window.grabWindow().save(str(Path(capture) / 'connections-busy-360.png'))
                host._state = 'idle'
                host.changed.emit()
                for name in ('revokePackagedApplication',):
                    item = find_item(self.window.contentItem(), name)
                    self.assertLessEqual(item.mapToScene(QPointF(item.width(), 0)).x(), self.window.width() - 24)
                if capture:
                    self.window.grabWindow().save(str(Path(capture) / 'connections-360.png'))
                self.manager.show()
                self.wait(lambda: self.manager.status()['visible'])
                find_item(root, 'extensionManagementPage').setProperty('selectedApplicationId', selected)
                QTest.qWait(20)
                remove = find_item(root, 'removeManagedApplication')
                remove.forceActiveFocus(Qt.TabFocusReason)
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                from PySide6.QtCore import QObject
                popup = root.findChild(QObject, 'applicationRemovalDialog')
                self.assertTrue(popup.property('visible'))
                cancel = find_item(self.window.contentItem(), 'cancelApplicationRemoval')
                cancel.forceActiveFocus(Qt.TabFocusReason)
                self.assertTrue(cancel.property('visualFocus'))
                if capture:
                    self.window.grabWindow().save(str(Path(capture) / 'removal-keyboard-360.png'))
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                self.assertFalse(popup.property('visible'))
                self.assertEqual(host.store.load(selected).id, selected)
                self.assertEqual(host._selected, '', 'Management browsing keeps no running app selected')
                remove.forceActiveFocus(Qt.TabFocusReason)
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                confirm = find_item(self.window.contentItem(), 'confirmApplicationRemoval')
                confirm.forceActiveFocus(Qt.TabFocusReason)
                QTest.keyClick(self.window, Qt.Key_Space)
                QTest.qWait(20)
                self.assertFalse(popup.property('visible'))
                self.assertTrue(host.feedback)
                self.click('workspaceEntry')
                self.assertFalse(host.feedback)
                self.click('canvasSettingsEntry')
                self.assertFalse(message.isVisible())

        def test_canvas_settings_navigation_theme_manager_and_version(self):
            from unittest.mock import patch
            from polaris_platform.metadata import VERSION
            mount_id = self.mount()
            self.window.resize(1300, 820)
            self.click('canvasSettingsEntry')
            self.assertTrue(find_item(self.window.rootObject(), 'canvasSettingsPage').isVisible())
            self.assertFalse(find_item(self.window.rootObject(), 'canvasViewport').isVisible())
            self.assertFalse(find_item(self.window.rootObject(), 'chooseComponentView').isVisible())
            self.assertEqual(find_item(self.window.rootObject(), 'canvasPageTitle').property('text'), '设置')
            self.assertEqual(find_item(self.window.rootObject(), 'canvasAboutVersion').property('text'), 'Polaris  v' + VERSION)
            from PySide6.QtCore import QObject
            self.manager.show()
            self.wait(lambda: self.manager.status()['visible'])
            self.click('installApplication')
            folder = self.window.rootObject().findChild(QObject, 'applicationDirectoryPicker')
            self.assertIsNotNone(folder)
            folder.setProperty('visible', False)
            self.app.processEvents()
            self.assertTrue(find_item(self.window.rootObject(), 'canvasSettingsPage').isVisible())
            self.assertEqual(self.window.rootObject().property('settingsSection'), 'extensions')
            self.assertTrue(find_item(self.window.rootObject(), 'extensionManagementPage').isVisible())
            self.assertFalse(hasattr(self.manager, '_view'))
            self.window.rootObject().setProperty('settingsSection', 'appearance')
            self.click('canvasAppearance_warm')
            self.assertEqual(self.canvas.actions.theme, 'warm')
            self.click('canvasAppearance_dark')
            self.assertEqual(self.canvas.actions.theme, 'dark')
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                self.window.grabWindow().save(str(Path(capture) / 'settings.png'))
                self.window.resize(720, 760)
                QTest.qWait(30)
                self.window.grabWindow().save(str(Path(capture) / 'settings-narrow.png'))
                self.window.resize(360, 760)
                QTest.qWait(30)
                self.assertGreater(find_item(self.window.rootObject(), 'canvasAppearance_light').y(), find_item(self.window.rootObject(), 'canvasAppearance_dark').y())
                self.window.grabWindow().save(str(Path(capture) / 'settings-compact.png'))
                self.window.resize(720, 760)
                QTest.qWait(20)
            self.click('workspaceEntry')
            self.assertFalse(find_item(self.window.rootObject(), 'canvasSettingsPage').isVisible())
            self.assertTrue(find_item(self.window.rootObject(), 'canvasViewport').isVisible())
            self.assertIn(mount_id, self.canvas.workbench.mounts)
            if capture:
                self.window.grabWindow().save(str(Path(capture) / 'workbench-narrow.png'))

        def test_application_switch_preserves_workbench_and_renders_inputs(self):
            import tempfile
            import json
            from polaris_platform.application import Application
            self.window.resize(1300, 820)
            mount_id = self.mount()
            capture = os.environ.get('POLARIS_UI_CAPTURE_DIR')
            if capture:
                Path(capture).mkdir(parents=True, exist_ok=True)
                self.window.grabWindow().save(str(Path(capture) / 'workbench.png'))
            with tempfile.TemporaryDirectory() as directory:
                host = self.canvas.application_host
                host.configure(directory)
                app = Application('示例应用')
                stable = self.runtime.status('org.example.counter')['instanceId']
                client = self.runtime.client('canvas')
                provider = self.runtime.component_instance('org.example.counter')
                provider._operations['get']['applicationBinding'] = 'instance'
                provider.port.advertise()
                app.bindings = {'read': dict(target=stable, installationId=stable, instanceId=stable,
                    operation='get', semantic=list(client.bind(stable, 'get').semantic))}
                app.flows = {'read': [{'alias': 'read', 'input': 'previous'}]}
                app.pages = [{'id': 'main', 'title': '计数示例', 'action': 'read',
                              'inputs': [{'name': 'label', 'label': '标签', 'default': '示例'}]}]
                host.importJson(json.dumps(app.as_dict()))
                self.assertFalse(host.error)
                self.wait(lambda: find_item(self.window.rootObject(), 'applicationEntry_' + app.id) is not None)
                host.select(app.id)
                self.wait(lambda: find_item(self.window.rootObject(), 'applicationInput_label') is not None)
                self.assertFalse(find_item(self.window.rootObject(), 'canvasViewport').isVisible())
                self.assertTrue(find_item(self.window.rootObject(), 'applicationPage').isVisible())
                self.assertFalse(find_item(self.window.rootObject(), 'chooseComponentView').isVisible())
                self.assertEqual(find_item(self.window.rootObject(), 'canvasPageTitle').property('text'), '示例应用')
                self.assertIn(mount_id, self.canvas.workbench.mounts)
                if capture:
                    QTest.qWait(80)
                    self.window.grabWindow().save(str(Path(capture) / 'application.png'))
                self.click('canvasSettingsEntry')
                self.assertFalse(find_item(self.window.rootObject(), 'applicationPage').isVisible())
                self.assertTrue(find_item(self.window.rootObject(), 'canvasSettingsPage').isVisible())
                self.click('workspaceEntry')
                self.assertTrue(find_item(self.window.rootObject(), 'canvasViewport').isVisible())
                self.assertIn(mount_id, self.canvas.workbench.mounts)

        def test_workbench_has_real_application_identity_and_owns_its_scene(self):
            from polaris_platform.application import Application
            from polaris_platform.builtin_apps.workbench import Workbench, WORKBENCH_ID
            from PySide6.QtQml import QQmlExpression
            workbench = self.canvas.workbench
            self.assertIsInstance(workbench, Application)
            self.assertIsInstance(workbench, Workbench)
            self.assertIs(self.runtime.application_component(WORKBENCH_ID), workbench)
            self.assertEqual(self.runtime.status(WORKBENCH_ID)['componentType'], 'org.polaris.workbench')
            self.assertEqual(json.loads(self.canvas.application_host.selectedJson)['applicationId'], WORKBENCH_ID)
            self.assertFalse(hasattr(self.canvas, 'mounts'))
            self.assertFalse(hasattr(self.canvas, 'cards'))
            self.assertEqual(Path(workbench._view.component.url().toLocalFile()).name, 'Workbench.qml')
            scope = QQmlExpression(workbench._view.context, workbench._view.root, 'typeof canvasActions')
            self.assertEqual(scope.evaluate()[0], 'undefined')
            scope = QQmlExpression(workbench._view.context, workbench._view.root, 'typeof applicationHost')
            self.assertEqual(scope.evaluate()[0], 'undefined')
            mount_id = self.mount()
            record = workbench.mounts[mount_id]
            self.assertEqual(record['context'].origin, self.context.origin)
            provider = self.runtime.component_instance('org.example.counter')
            self.click('canvasSettingsEntry')
            self.assertFalse(workbench._view.root.isEnabled())
            self.assertEqual(self.runtime.status(WORKBENCH_ID)['state'], 'running')
            self.assertIs(workbench.mounts[mount_id], record)
            self.click('workspaceEntry')
            self.assertTrue(workbench._view.root.isEnabled())
            self.assertIs(provider, self.runtime.component_instance('org.example.counter'))

        def test_workbench_reparent_releases_old_handles_and_rebuilds_with_original_context(self):
            from PySide6.QtQuick import QQuickItem
            mount_id = self.mount()
            workbench = self.canvas.workbench
            original = workbench.mounts[mount_id]
            original_handle = original['handle']
            original_context = original['context']
            layout = dict(x=61, y=73, width=403, height=281, collapsed=False)
            self.call('canvas', 'layout', dict(mountId=mount_id, **layout))
            provider = self.runtime.component_instance('org.example.counter')
            body = QQuickItem(self.window.rootObject())
            body.setParentItem(self.window.rootObject())
            body.setWidth(800)
            body.setHeight(600)
            header = QQuickItem(self.window.rootObject())
            header.setParentItem(self.window.rootObject())
            header.setWidth(240)
            header.setHeight(34)
            old_view = workbench._view
            self.canvas.application_host.attachView(body)
            self.canvas.application_host.attachBuiltinHeader(header)
            self.wait(lambda: len(workbench.mounts) == 1 and all(r['state'] == 'mounted' for r in workbench.mounts.values()))
            rebuilt = next(iter(workbench.mounts.values()))
            self.assertTrue(original['cancelled'])
            self.assertNotIn(original_handle, provider._views)
            self.assertIs(rebuilt['context'], original_context)
            self.assertEqual(rebuilt['layout'], layout)
            self.assertEqual(rebuilt['layoutId'], original['layoutId'])
            self.assertIsNone(old_view.root)
            self.assertIs(workbench._view.parent, body)
            self.assertIs(workbench._view.header_parent, header)
            self.assertIs(workbench._view.context.engine(), workbench._view.engine)
            self.assertEqual(self.runtime.status('org.example.counter')['state'], 'running')

        def test_workbench_explicit_navigation_restart_restores_saved_layout(self):
            from polaris_platform.builtin_apps.workbench import WORKBENCH_ID
            self.prepare_approval()
            self.approval_click('confirmPermission')
            self.wait(lambda: bool(self.canvas.workbench.mounts) and all(r['state'] == 'mounted' for r in self.canvas.workbench.mounts.values()))
            mount_id = next(iter(self.canvas.workbench.mounts))
            layout = dict(x=57, y=71, width=410, height=277, collapsed=False)
            self.call('canvas', 'layout', dict(mountId=mount_id, **layout))
            workbench = self.canvas.workbench
            old = workbench.mounts[mount_id]
            self.runtime.stop_application(WORKBENCH_ID)
            self.assertFalse(workbench.running)
            self.assertFalse(workbench._view.root.isEnabled())
            self.canvas.application_host.refreshConnections()
            self.assertFalse(workbench.running)
            self.assertFalse(workbench._view.root.isVisible())
            # A real navigation click is the new local input authority.
            self.click('workspaceEntry')
            self.wait(lambda: bool(workbench.mounts) and all(r['state'] == 'mounted' for r in workbench.mounts.values()))
            rebuilt = next(iter(workbench.mounts.values()))
            self.assertEqual(rebuilt['layout'], layout)
            self.assertNotEqual(rebuilt['handle'], old['handle'])
            self.assertTrue(workbench._view.root.isEnabled())

        def test_workbench_stop_cancels_its_approval_and_restart_has_fresh_epoch(self):
            from polaris_platform.builtin_apps.workbench import WORKBENCH_ID
            self.prepare_approval()
            workbench = self.canvas.workbench
            old_epoch = workbench._generation
            tokens = list(workbench._approval_tokens.values())
            reasons = list(workbench._approvals)
            self.assertTrue(tokens)
            self.runtime.stop_application(WORKBENCH_ID)
            self.wait(lambda: self.manager.bridge.planJson == '[]')
            self.assertFalse(workbench._approvals)
            self.assertFalse(workbench._approval_tokens)
            self.assertFalse(set(reasons) & self.canvas._holds)
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.runtime.start_application(WORKBENCH_ID)
            self.canvas.application_host.select(WORKBENCH_ID)
            self.assertNotEqual(old_epoch, workbench._generation)
            for token in tokens:
                self.manager.bridge.cancel_approval(token)
            self.assertFalse(workbench.mounts)
            self.assertFalse(self.runtime.authorization.scope('canvas'))
            self.prepare_approval()
            self.approval_click('confirmPermission')
            self.wait(lambda: bool(workbench.mounts) and all(r['state'] == 'mounted' for r in workbench.mounts.values()))

        def test_legacy_layout_pins_default_identity_and_single_conflicts_preserve_intent(self):
            from copy import deepcopy
            from PySide6.QtTest import QSignalSpy
            mount_id = self.mount()
            record = self.canvas.workbench.mounts[mount_id]
            saved = deepcopy(self.canvas._storage.entries[record['layoutId']])
            saved.pop('stableInstanceId', None)
            saved['target'] = 'org.example.counter'
            self.call('canvas', 'unmount', {'mountId': mount_id})
            self.canvas._storage.entries[saved['id']] = saved
            self.canvas.workbench.restore_layout(self.context)
            self.wait(lambda: len(self.canvas.workbench.mounts) == 1)
            stable = self.runtime.status('org.example.counter')['instanceId']
            self.assertEqual(saved['stableInstanceId'], stable)
            self.assertEqual(saved['target'], stable)
            provider = self.runtime.component_instance('org.example.counter')
            provider.views[0]['instancePolicy'] = 'single'
            provider.port.advertise()
            duplicate = deepcopy(saved)
            duplicate['id'] = 'duplicate-layout'
            self.canvas._storage.entries[duplicate['id']] = duplicate
            failed = QSignalSpy(self.canvas.actions.failed)
            self.canvas.workbench.restore_layout(self.context)
            self.assertEqual(len(self.canvas.workbench.mounts), 1)
            self.assertEqual(len(self.canvas._storage.entries), 2)
            self.assertGreater(failed.count(), 0)

    unittest.main()
