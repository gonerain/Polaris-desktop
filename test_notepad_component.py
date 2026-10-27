from headless_test_support import HeadlessQtTestCase

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


class NotepadComponentTests(HeadlessQtTestCase):
    def setUp(self):
        self.window = self.load_window('''
import QtQuick
import "components"
Window {
    width: 260; height: 260; visible: true
    ComponentBoard {
        id: board; anchors.fill: parent
        panelSize: Qt.size(260, 260); panelCount: 1
    }
    Component { id: factory; Notepad { objectName: "notepad" } }
    Component.onCompleted: board.request(factory)
}
''')
        self.editor = self.item(self.window, 'editor')

    def test_notepad_can_still_be_requested_as_a_panel_component(self):
        self.editor.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key_A)
        QTest.keyClick(self.window, Qt.Key_Return)
        QTest.keyClick(self.window, Qt.Key_B)
        self.assertEqual(self.editor.property('text'), 'a\nb')
        self.editor.setProperty('text', '记录\n' * 100)
        self.app.processEvents()
        self.assertGreater(self.editor.property('contentHeight'), self.window.height())
