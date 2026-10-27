from headless_test_support import HeadlessQtTestCase

from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtTest import QTest


HARNESS = '''
import QtQuick
import "components"
Window {
    id: win
    width: 200; height: 200; visible: true; color: "white"
    property int born: 0
    property int insideHits: 0
    property int outsideHits: 0
    property color paintColor: "blue"
    property var handle
    property bool releaseNow: false
    property bool failedCreation: false
    property bool duplicateRelease: false
    readonly property int freeCount: board.freePanelCount
    onReleaseNowChanged: {
        board.release(handle)
        duplicateRelease = board.release(handle)
    }
    Rectangle {
        anchors.fill: parent; color: "green"
        MouseArea { anchors.fill: parent; onClicked: win.outsideHits++ }
    }
    ComponentBoard { id: board; objectName: "board"; panelSize: Qt.size(30, 30); panelCount: 4; gap: 6 }
    Component {
        id: tile
        Rectangle {
            color: win.paintColor
            Component.onCompleted: win.born++
            HANDLER
        }
    }
    Component {
        id: invalidTile
        QtObject { property real x; property real y; property real width; property real height }
    }
    Component.onCompleted: {
        handle = board.request(tile, {cells: SHAPE})
        failedCreation = !board.request(invalidTile).ok
    }
}
'''


class ComponentBoardTests(HeadlessQtTestCase):
    def create_board(self, shape='[[0,0],[1,0],[0,1]]', handler=None):
        handler = handler or 'MouseArea { anchors.fill: parent; onClicked: win.insideHits++ }'
        return self.load_window(HARNESS.replace('SHAPE', shape).replace('HANDLER', handler))

    def pixel(self, window, x, y):
        QTest.qWait(30)
        image = window.grabWindow()
        scale = window.devicePixelRatio()
        return image.pixelColor(round(x * scale), round(y * scale)).name()

    def wheel(self, window, point):
        # Qt 6.8 的 QTest.wheelEvent 底层使用本机像素坐标。
        QTest.wheelEvent(window, QPointF(point) * window.devicePixelRatio(), QPoint(0, 120))

    def test_irregular_pixels_holes_and_single_instance(self):
        window = self.create_board()
        self.assertEqual(window.property('born'), 1)
        self.assertEqual(window.property('freeCount'), 1)
        self.assertTrue(window.property('failedCreation'))
        for point in ((15, 15), (50, 15), (15, 50), (33, 15), (15, 33)):
            self.assertEqual(self.pixel(window, *point), '#0000ff')
        for point in ((50, 50), (33, 33), (90, 90)):
            self.assertEqual(self.pixel(window, *point), '#008000')

    def test_mouse_area_and_tap_handler_do_not_steal_hole_clicks(self):
        for handler in ('MouseArea { anchors.fill: parent; onClicked: win.insideHits++ }',
                        'TapHandler { onTapped: win.insideHits++ }'):
            with self.subTest(handler=handler):
                window = self.create_board(handler=handler)
                QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(15, 15))
                QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(50, 50))
                self.assertEqual(window.property('insideHits'), 1)
                self.assertEqual(window.property('outsideHits'), 1)

    def test_fragments_preserve_nonuniform_content_coordinates_and_orientation(self):
        window = self.create_board(handler='''
            Rectangle { width: 33; height: 33; color: "red" }
            Rectangle { y: 33; width: 33; height: 33; color: "yellow" }
        ''')
        self.assertEqual(self.pixel(window, 15, 15), '#ff0000')
        self.assertEqual(self.pixel(window, 50, 15), '#0000ff')
        self.assertEqual(self.pixel(window, 15, 50), '#ffff00')
        self.assertEqual(self.pixel(window, 50, 50), '#008000')

    def test_live_content_changes_update_all_fragments(self):
        window = self.create_board()
        window.setProperty('paintColor', '#cc00cc')
        self.assertEqual(self.pixel(window, 15, 15), '#cc00cc')
        self.assertEqual(self.pixel(window, 15, 50), '#cc00cc')
        self.assertEqual(self.pixel(window, 50, 50), '#008000')
        self.assertEqual(window.property('born'), 1)

    def test_irregular_regions_and_geometry_adapt_to_board_size(self):
        source = HARNESS.replace(
            'ComponentBoard { id: board; objectName: "board"; panelSize: Qt.size(30, 30); panelCount: 4; gap: 6 }',
            'ComponentBoard { id: board; objectName: "board"; anchors.fill: parent; panelSize: Qt.size(30, 30); panelCount: 4; gap: 6 }'
        ).replace('SHAPE', '[[0,0],[1,0],[0,1]]').replace(
            'HANDLER', 'property var context: parent.panelContext\n            MouseArea { anchors.fill: parent; onClicked: win.insideHits++ }'
        )
        window = self.load_window(source)
        context = window.property('handle').toVariant()['item'].property('context').toVariant()
        self.assertEqual((context['width'], context['height']), (200, 200))
        self.assertEqual(len(context['regions']), 2)
        self.assertEqual(window.property('freeCount'), 1)
        self.assertEqual(self.pixel(window, 50, 50), '#0000ff')
        self.assertEqual(self.pixel(window, 50, 150), '#0000ff')
        self.assertEqual(self.pixel(window, 150, 50), '#0000ff')
        self.assertEqual(self.pixel(window, 150, 150), '#008000')
        QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(150, 150))
        self.assertEqual(window.property('outsideHits'), 1)

    def test_rectangular_span_and_disconnected_shape(self):
        window = self.create_board('[[0,0],[1,0],[0,1],[1,1]]')
        self.assertEqual(self.pixel(window, 33, 33), '#0000ff')
        self.assertEqual(window.property('freeCount'), 0)
        window = self.create_board('[[0,0],[1,1]]')
        self.assertEqual(self.pixel(window, 50, 50), '#0000ff')
        self.assertEqual(self.pixel(window, 50, 15), '#008000')

    def test_release_is_immediate_and_cannot_be_repeated(self):
        window = self.create_board()
        window.setProperty('releaseNow', True)
        self.assertEqual(window.property('freeCount'), 4)
        self.assertFalse(window.property('duplicateRelease'))
        self.assertEqual(self.pixel(window, 15, 15), '#008000')

    def test_wheel_events_in_the_hole_reach_the_underlying_item(self):
        for handler in ('MouseArea { anchors.fill: parent; onWheel: win.insideHits++ }',
                        'WheelHandler { onWheel: win.insideHits++ }'):
            with self.subTest(handler=handler):
                source = HARNESS.replace('SHAPE', '[[0,0],[1,0],[0,1]]').replace(
                    'HANDLER', handler
                ).replace('onClicked: win.outsideHits++', 'onWheel: win.outsideHits++')
                window = self.load_window(source)
                for point in (QPoint(15, 15), QPoint(50, 50)):
                    self.wheel(window, point)
                self.assertEqual(window.property('insideHits'), 1)
                self.assertEqual(window.property('outsideHits'), 1)

    def test_component_hit_masks_and_their_qml_bindings_are_preserved(self):
        window = self.create_board(handler='''
            property bool narrow: true
            QtObject { id: smallMask; function contains(p: point): bool { return p.x < 20 } }
            QtObject { id: largeMask; function contains(p: point): bool { return true } }
            containmentMask: narrow ? smallMask : largeMask
            TapHandler { onTapped: win.insideHits++ }
        ''')
        item = window.property('handle').toVariant()['item']
        QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(50, 15))
        self.assertEqual(window.property('insideHits'), 0)
        item.setProperty('narrow', False)
        QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(50, 15))
        self.assertEqual(window.property('insideHits'), 1)
        item.setProperty('narrow', True)
        QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(50, 15))
        self.assertEqual(window.property('insideHits'), 1)
        self.assertEqual(window.property('outsideHits'), 2)

    def test_nested_boards_combine_input_boundaries(self):
        source = HARNESS.replace('SHAPE', '[[0,0],[1,0],[0,1]]').replace('HANDLER', '''
            ComponentBoard {
                panelSize: Qt.size(30, 30); panelCount: 4; gap: 6
                Component {
                    id: innerFactory
                    Rectangle { color: "blue"; WheelHandler { onWheel: win.insideHits++ } }
                }
                Component.onCompleted: request(innerFactory, {cells: [[0,0],[1,0],[0,1]]})
            }
        ''').replace('onClicked: win.outsideHits++', 'onWheel: win.outsideHits++')
        window = self.load_window(source)
        self.wheel(window, QPoint(15, 15))
        self.wheel(window, QPoint(50, 50))
        self.assertEqual(window.property('insideHits'), 1)
        self.assertEqual(window.property('outsideHits'), 1)

    def test_text_input_inside_an_irregular_component(self):
        window = self.create_board(handler='TextInput { objectName: "input"; anchors.fill: parent; focus: true }')
        field = self.item(window, 'input')
        field.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_A)
        QTest.keyClick(window, Qt.Key_B)
        self.assertEqual(field.property('text'), 'ab')

    def test_hole_can_be_owned_by_another_component_behind_the_irregular_one(self):
        source = HARNESS.replace('SHAPE', '[[0,0],[1,0],[0,1]]').replace(
            'HANDLER', 'MouseArea { anchors.fill: parent; onClicked: win.insideHits++ }'
        ).replace('Component.onCompleted: {\n        handle =', '''
    Component {
        id: holeFactory
        Rectangle {
            color: "yellow"
            MouseArea { anchors.fill: parent; onClicked: win.outsideHits++ }
        }
    }
    Component.onCompleted: {
        handle =''').replace('failedCreation = !board.request(invalidTile).ok', '''
        failedCreation = !board.request(invalidTile).ok
        board.request(holeFactory)
        handle.host.z = 10
        ''')
        window = self.load_window(source)
        self.assertEqual(self.pixel(window, 50, 50), '#ffff00')
        QTest.mouseClick(window, Qt.LeftButton, pos=QPoint(50, 50))
        self.assertEqual(window.property('insideHits'), 0)
        self.assertEqual(window.property('outsideHits'), 1)

    def test_hover_does_not_extend_into_the_hole(self):
        window = self.create_board(handler='HoverHandler { objectName: "hover" }')
        handler = window.findChild(QObject, 'hover')
        QTest.mouseMove(window, QPoint(15, 15))
        self.assertTrue(handler.property('hovered'))
        QTest.mouseMove(window, QPoint(50, 50))
        self.assertFalse(handler.property('hovered'))

    def test_components_can_read_their_local_region_context(self):
        window = self.create_board(handler='property var context: parent.panelContext')
        handle = window.property('handle').toVariant()
        context = handle['item'].property('context').toVariant()
        self.assertEqual((context['width'], context['height']), (66, 66))
        self.assertEqual(len(context['cells']), 3)
        self.assertEqual(len(context['regions']), 2)

    def test_animation_is_live_and_keeps_the_hole_transparent(self):
        source = HARNESS.replace('SHAPE', '[[0,0],[1,0],[0,1]]').replace('HANDLER', '''
            property real progress: 0
            property bool animate: false
            NumberAnimation on progress { from: 0; to: 1; duration: 160; running: animate }
            onProgressChanged: win.paintColor = Qt.rgba(progress, 0, 1 - progress, 1)
        ''')
        window = self.load_window(source)
        first = self.pixel(window, 15, 15)
        window.property('handle').toVariant()['item'].setProperty('animate', True)
        QTest.qWait(180)
        self.assertNotEqual(self.pixel(window, 15, 15), first)
        self.assertEqual(self.pixel(window, 15, 50), '#ff0000')
        self.assertEqual(self.pixel(window, 50, 50), '#008000')
        self.assertEqual(window.property('born'), 1)

    def test_drag_started_inside_can_release_outside_without_sticking(self):
        window = self.create_board(handler='MouseArea { objectName: "dragArea"; anchors.fill: parent }')
        area = self.item(window, 'dragArea')
        QTest.mousePress(window, Qt.LeftButton, pos=QPoint(15, 15))
        self.assertTrue(area.property('pressed'))
        QTest.mouseMove(window, QPoint(50, 50))
        QTest.mouseRelease(window, Qt.LeftButton, pos=QPoint(50, 50))
        self.assertFalse(area.property('pressed'))
