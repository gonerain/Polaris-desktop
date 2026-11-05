import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Button {
    id: control
    property var canvasPalette: null
    property string glyph: "plus"
    property bool primary: false
    property bool truncateLabel: false
    property string hint: text
    implicitHeight: 34
    implicitWidth: text.length ? label.implicitWidth + 26 : 32
    padding: 0
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: hint
    ToolTip.visible: hovered && hint.length > 0
    ToolTip.text: hint
    ToolTip.delay: 650
    contentItem: Item {
        opacity: control.enabled ? 1 : 0.42
        Row {
            id: label
            spacing: 6
            anchors.centerIn: parent
            CanvasIcon { anchors.verticalCenter: parent.verticalCenter; kind: control.glyph; ink: control.primary ? control.canvasPalette.accentInk : control.canvasPalette ? control.canvasPalette.muted : "#697386" }
            Text { textFormat: Text.PlainText; width: control.truncateLabel ? Math.min(implicitWidth, Math.max(0, control.width - 48)) : implicitWidth; elide: Text.ElideRight; visible: control.text.length > 0; text: control.text; anchors.verticalCenter: parent.verticalCenter; color: control.primary ? control.canvasPalette.accentInk : control.canvasPalette ? control.canvasPalette.ink : "#1f2937"; font.pixelSize: 13; font.weight: Font.Medium }
        }
    }
    background: Rectangle {
        radius: 8
        opacity: control.enabled ? 1 : 0.45
        color: control.primary ? (control.down || control.hovered ? control.canvasPalette.accentHover : control.canvasPalette.accent) : control.down ? (control.canvasPalette ? control.canvasPalette.pressed : "#dde6f6") : control.hovered ? (control.canvasPalette ? control.canvasPalette.hover : "#eaf0f9") : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: control.canvasPalette ? control.canvasPalette.focus : "#4263c7"
    }
}
