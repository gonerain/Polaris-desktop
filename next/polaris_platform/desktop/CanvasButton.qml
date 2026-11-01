import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: control
    property var canvasPalette: null
    property string glyph: "plus"
    property bool primary: false
    property string hint: text
    implicitHeight: 30
    implicitWidth: text.length ? label.implicitWidth + 18 : 30
    padding: 0
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: hint
    ToolTip.visible: hovered && hint.length > 0
    ToolTip.text: hint
    ToolTip.delay: 650
    contentItem: Item {
        Row {
            id: label
            spacing: 6
            anchors.centerIn: parent
            CanvasIcon { anchors.verticalCenter: parent.verticalCenter; kind: control.glyph; ink: control.canvasPalette ? control.canvasPalette.ink : "#646b5e" }
            Text { visible: text.length > 0; text: control.text; anchors.verticalCenter: parent.verticalCenter; color: control.canvasPalette ? control.canvasPalette.ink : "#454b40"; font.pixelSize: 13; font.weight: Font.Medium }
        }
    }
    background: Rectangle {
        radius: 8
        color: control.down ? (control.canvasPalette ? control.canvasPalette.pressed : "#e1e4da") : control.hovered || control.primary ? (control.canvasPalette ? control.canvasPalette.hover : "#e9ece2") : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: control.canvasPalette ? control.canvasPalette.focus : "#939d86"
    }
}
