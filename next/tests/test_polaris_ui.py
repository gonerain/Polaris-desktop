"""Public Polaris.Ui controls tested in a real, isolated Qt Quick engine."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if __name__ != '__main__':
    class PolarisUiProcessTests(unittest.TestCase):
        def test_public_qml_controls(self):
            if importlib.util.find_spec('PySide6') is None:
                self.skipTest('Optional PySide6 is not installed')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    from PySide6.QtCore import QObject, QUrl, Qt, QPointF
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest, QSignalSpy
    from polaris_platform.ui import configure_qml_engine
    QML = ROOT / 'polaris_platform/ui/examples/Controls.qml'

    def find(item, name):
        if item.objectName() == name: return item
        for child in item.childItems():
            result = find(child, name)
            if result is not None: return result

    class PublicControlTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])
        def setUp(self):
            self.view = QQuickView()
            self.view.setResizeMode(QQuickView.SizeRootObjectToView)
            configure_qml_engine(self.view.engine())
            self.view.setSource(QUrl.fromLocalFile(str(QML)))
            self.assertFalse(self.view.errors(), [error.toString() for error in self.view.errors()])
            self.view.resize(800, 660)
            self.view.show()
            self.view.requestActivate()
            QTest.qWait(20)
            self.root = self.view.rootObject()
        def tearDown(self):
            self.view.close()
            self.view.deleteLater()
            self.app.processEvents()
        def item(self, name):
            item = find(self.root, name)
            self.assertIsNotNone(item, name)
            return item
        def click(self, name):
            item = self.item(name)
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
            QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier, point)
            self.app.processEvents()
        def type_text(self, value):
            for character in value:
                QTest.keyClick(self.view, Qt.Key(ord(character.upper())), Qt.ShiftModifier if character.isupper() else Qt.NoModifier)
        def test_button_mouse_keyboard_focus_and_disabled(self):
            button = self.item('uiButton')
            spy = QSignalSpy(button.clicked)
            self.click('uiButton')
            self.assertEqual(spy.count(), 1)
            self.item('uiField').forceActiveFocus()
            button.forceActiveFocus(Qt.TabFocusReason)
            self.app.processEvents()
            self.assertTrue(button.property('visualFocus'))
            QTest.keyClick(self.view, Qt.Key_Space)
            self.assertEqual(spy.count(), 2)
            self.click('uiDisabledButton')
            self.assertEqual(self.root.property('actionCount'), 2)
            navigation = self.item('uiNavigation')
            navigation_spy = QSignalSpy(navigation.clicked)
            navigation.forceActiveFocus(Qt.TabFocusReason)
            QTest.keyClick(self.view, Qt.Key_Space)
            self.assertEqual(navigation_spy.count(), 1)
            navigation.setProperty('enabled', False)
            QTest.keyClick(self.view, Qt.Key_Space)
            self.assertEqual(navigation_spy.count(), 1)
            disabled = self.item('uiDisabledNavigation')
            self.assertFalse(disabled.property('enabled'))
        def test_text_edit_selection_disabled_and_combo_keyboard(self):
            field = self.item('uiField')
            self.click('uiField')
            self.type_text('polaris')
            self.assertEqual(field.property('text'), 'polaris')
            QTest.keyClick(self.view, Qt.Key_A, Qt.ControlModifier)
            self.type_text('ready')
            self.assertEqual(field.property('text'), 'ready')
            field.setProperty('enabled', False)
            self.type_text('ignored')
            self.assertEqual(field.property('text'), 'ready')
            combo = self.item('uiCombo')
            combo.forceActiveFocus(Qt.TabFocusReason)
            QTest.keyClick(self.view, Qt.Key_Down)
            self.assertEqual(combo.property('currentIndex'), 1)
            combo.setProperty('enabled', False)
            QTest.keyClick(self.view, Qt.Key_Down)
            self.assertEqual(combo.property('currentIndex'), 1)
        def test_theme_response_truncation_narrow_layout_and_scrollbar(self):
            field = self.item('uiField')
            before = field.property('color')
            self.click('uiThemeLight')
            self.assertEqual(self.root.property('mode'), 'light')
            self.assertNotEqual(field.property('color'), before)
            self.click('uiThemeWarm')
            self.assertEqual(self.root.property('mode'), 'warm')
            self.view.resize(520, 740)
            self.app.processEvents()
            button = self.item('uiTruncatedButton')
            end = button.mapToScene(QPointF(button.width(), 0)).x()
            self.assertLessEqual(end, self.view.width())
            self.item('uiScrollArea').setProperty('contentHeight', 1000)
            self.app.processEvents()
            bar = self.item('uiScrollBar')
            self.assertTrue(bar.isVisible())
            bar.setProperty('position', .5)
            self.assertGreater(bar.property('position'), 0)
        def test_combo_listmodel_text_role_and_object_array(self):
            from PySide6.QtQml import QQmlComponent
            from PySide6.QtCore import QMetaObject
            component = QQmlComponent(self.view.engine())
            component.setData(b"import QtQuick\nimport Polaris.Ui 1.0 as Ui\nItem { width: 320; height: 160; Ui.Theme { id: colors } ListModel { id: rows; ListElement { label: 'First'; code: 'a' } ListElement { label: 'Second'; code: 'b' } } Ui.ComboBox { objectName: 'roleCombo'; theme: colors; width: 250; textRole: 'label'; model: rows } }", QUrl())
            item = component.create()
            self.assertIsNotNone(item, [error.toString() for error in component.errors()])
            item.setParent(self.root)
            item.setParentItem(self.root)
            combo = find(item, 'roleCombo')
            self.assertEqual(combo.property('displayText'), 'First')
            from PySide6.QtQml import QQmlExpression, qmlContext
            def evaluate(script):
                expression = QQmlExpression(qmlContext(combo), combo, script)
                value, undefined = expression.evaluate()
                self.assertFalse(expression.hasError(), expression.error().toString())
                return value
            def option_texts():
                import json
                return json.loads(evaluate("(function() { var result = []; var rows = popup.contentItem.contentItem.children; for(var i=0;i<rows.length;i++) if(rows[i].text !== undefined) result.push(rows[i].text); return JSON.stringify(result) })()"))
            evaluate('popup.open()')
            QTest.qWait(20)
            self.assertIn('First', option_texts())
            self.assertIn('Second', option_texts())
            evaluate('popup.close()')
            combo.setProperty('model', [{'label':'Array first', 'code':'x'}, {'label':'Array second', 'code':'y'}])
            self.assertEqual(combo.property('displayText'), 'Array first')
            evaluate('popup.open()')
            QTest.qWait(20)
            self.assertIn('Array second', option_texts())
            evaluate('popup.close()')
        def test_button_default_text_only_width_mouse_and_keyboard(self):
            button = self.item('uiThemeLight')
            self.assertEqual(button.property('glyph'), '')
            from PySide6.QtQml import QQmlExpression, qmlContext
            expression = QQmlExpression(qmlContext(button), button, 'implicitWidth === contentItem.children[0].children[1].implicitWidth + 26')
            self.assertTrue(expression.evaluate()[0])
            self.click('uiThemeLight')
            self.assertEqual(self.root.property('mode'), 'light')
            self.root.setProperty('mode', 'dark')
            self.item('uiField').forceActiveFocus()
            button.forceActiveFocus(Qt.TabFocusReason)
            QTest.keyClick(self.view, Qt.Key_Space)
            self.assertEqual(self.root.property('mode'), 'light')
        def test_scrollbar_honors_all_native_visibility_policies(self):
            from PySide6.QtQml import QQmlExpression, qmlContext
            bar = self.item('uiScrollBar')
            def evaluate(script):
                expression = QQmlExpression(qmlContext(bar), bar, script)
                expression.evaluate()
                self.assertFalse(expression.hasError(), expression.error().toString())
                self.app.processEvents()
            evaluate('size = 1; policy = 2')  # Qt Controls.ScrollBar.AlwaysOn
            self.assertTrue(bar.isVisible())
            evaluate('size = 0.2; policy = 1')  # AlwaysOff
            self.assertFalse(bar.isVisible())
            evaluate('policy = 0')  # AsNeeded
            self.assertTrue(bar.isVisible())
            evaluate('size = 1')
            self.assertFalse(bar.isVisible())
        def test_showcase_themes_and_independent_views(self):
            capture = os.environ.get('POLARIS_UI_LIBRARY_CAPTURE')
            for mode in ('dark', 'light', 'warm'):
                self.root.setProperty('mode', mode)
                QTest.qWait(30)
                if capture:
                    directory = Path(capture)
                    directory.mkdir(parents=True, exist_ok=True)
                    self.view.grabWindow().save(str(directory / ('controls-' + mode + '.png')))
            other = QQuickView()
            configure_qml_engine(other.engine())
            other.setSource(QUrl.fromLocalFile(str(QML)))
            self.assertFalse(other.errors())
            self.assertEqual(other.rootObject().property('mode'), 'dark')
            self.assertEqual(self.root.property('mode'), 'warm')
            other.close()
            other.deleteLater()

    unittest.main()
