"""Black-box Qt interactions for canvas sessions and third-party native views."""
import os
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
                self.wait(lambda: self.canvas.mounts[identity]['state'] == 'mounted')
                record = self.canvas.mounts[identity]
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
                self.wait(lambda: identity not in self.canvas.mounts)

        def test_text_cards_and_explicit_arrange_do_not_overlap(self):
            self.call('canvas', 'set_cards', {'cards': [{'title': 'One'}, {'title': 'Two'}]})
            first, second = self.mount(), self.mount()
            self.assertGreaterEqual(self.canvas.mounts[first]['layout']['y'], 168)
            self.canvas.actions.arrange(1000)
            layouts = [self.canvas.mounts[identity]['layout'] for identity in (first, second)]
            self.assertTrue(all(row['y'] >= 168 for row in layouts))
            self.assertGreaterEqual(layouts[1]['x'], layouts[0]['x'] + layouts[0]['width'])

        def test_overflow_navigation_keeps_cards_reachable_after_resize(self):
            self.window.resize(950, 620)
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
            original_y = self.canvas.mounts[mounts[-1]]['layout']['y']
            self.wait(lambda: viewport.property('contentY') > 0 and title_visible(last))
            self.assertEqual(last.y(), original_y, 'Scrolling must preserve the logical card layout')
            self.assertEqual((last.width(), last.height()), (380, 340), 'New native cards must leave useful space for their content')
            self.assertEqual(viewport.property('contentWidth'), viewport.width())
            self.assertFalse(find_item(self.window.rootObject(), 'canvasHorizontalScroll').isVisible())
            self.window.resize(380, 280)
            self.wait(lambda: viewport.width() == 284 and viewport.height() == 166)
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
            self.assertEqual(self.canvas.mounts[mounts[1]]['layout']['collapsed'], True)
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
            self.wait(lambda: mounts[-1] not in self.canvas.mounts)

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
            self.wait(lambda: find_item(self.manager._view.contentItem(), 'confirmPermission') is not None)
            _mouseMove(self.window, QPoint(-20, -20))
            QTest.qWait(280)
            self.assertTrue(self.window.isVisible(), 'An external permission confirmation must hold the canvas')
            self.assertEqual(self.canvas.status()['sessionId'], session)
            self.assertFalse(self.runtime.authorization.scope('canvas'), 'Choosing a view must not grant permissions')
            self.assertFalse(self.canvas.status()['mounts'])

        def approval_click(self, name):
            button = find_item(self.manager._view.contentItem(), name)
            self.assertIsNotNone(button)
            point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
            _mouseClick(self.manager._view, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))

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
            self.approval_click('confirmPermission')
            self.wait(lambda: not self.manager.bridge.busy and self.manager.bridge.planJson == '[]')
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

    unittest.main()
